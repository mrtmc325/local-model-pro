from __future__ import annotations

import ipaddress
import re
import ssl
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html as lxml_html

try:  # pragma: no cover - optional dependency fallback
    from readability import Document as ReadabilityDocument
except Exception:  # pragma: no cover - import fallback
    ReadabilityDocument = None  # type: ignore[assignment]

_ALLOWED_SCHEMES: Final[set[str]] = {"http", "https"}
_LOCAL_HOSTS: Final[set[str]] = {"localhost", "localhost.localdomain"}
_MAX_REDIRECTS: Final[int] = 4
_MAX_EXTRACTED_CHARS: Final[int] = 160_000
_BOILERPLATE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*(menu|navigation|skip to content)\s*$", re.IGNORECASE),
    re.compile(r"\b(cookie|privacy policy|terms of (service|use))\b", re.IGNORECASE),
    re.compile(r"\b(sign in|log in|subscribe|newsletter)\b", re.IGNORECASE),
    re.compile(r"\b(advertisement|sponsored content)\b", re.IGNORECASE),
    re.compile(r"\ball rights reserved\b", re.IGNORECASE),
)


class URLReviewError(RuntimeError):
    """Raised when URL review fetch/validation fails."""


@dataclass(frozen=True)
class ReviewedPage:
    requested_url: str
    final_url: str
    title: str
    text: str
    content_type: str
    fetched_at: str


class URLReviewClient:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> None:
        self._timeout_seconds = max(3, int(timeout_seconds))
        self._max_bytes = max(32_000, int(max_bytes))
        # Use system trust roots for outbound HTTPS validation.
        self._ssl_context = ssl.create_default_context()

    @staticmethod
    def _is_forbidden_ip(value: str) -> bool:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return True
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        )

    @staticmethod
    def _validate_hostname(hostname: str) -> None:
        host = hostname.strip().lower().rstrip(".")
        if not host:
            raise URLReviewError("URL host is required.")
        if host in _LOCAL_HOSTS or host.endswith(".local"):
            raise URLReviewError("Local hosts are blocked.")

        try:
            ipaddress.ip_address(host)
            ip_candidates = [host]
        except ValueError:
            try:
                infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise URLReviewError(f"Unable to resolve host: {host}") from exc
            ip_candidates = []
            for item in infos:
                address = item[4][0]
                if address not in ip_candidates:
                    ip_candidates.append(address)

        if not ip_candidates:
            raise URLReviewError("Host resolution produced no addresses.")
        for ip in ip_candidates:
            if URLReviewClient._is_forbidden_ip(ip):
                raise URLReviewError("URL resolves to a blocked network target.")

    @staticmethod
    def _validate_url(url: str) -> str:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise URLReviewError("Only http/https URLs are allowed.")
        if parsed.username or parsed.password:
            raise URLReviewError("URLs with embedded credentials are not allowed.")
        if not parsed.netloc:
            raise URLReviewError("URL host is missing.")
        host = parsed.hostname or ""
        URLReviewClient._validate_hostname(host)
        return parsed.geturl()

    @staticmethod
    def _is_supported_content_type(value: str) -> bool:
        content_type = value.split(";", 1)[0].strip().lower()
        if content_type.startswith("text/"):
            return True
        return content_type in {"application/xhtml+xml", "application/xml"}

    @staticmethod
    def _decode_body(raw: bytes, content_type: str) -> str:
        charset = ""
        for token in content_type.split(";"):
            token = token.strip().lower()
            if token.startswith("charset="):
                charset = token.split("=", 1)[1].strip()
                break

        if charset:
            try:
                return raw.decode(charset, errors="ignore")
            except LookupError:
                pass

        for fallback in ("utf-8", "latin-1"):
            try:
                return raw.decode(fallback, errors="ignore")
            except UnicodeDecodeError:
                continue
        return ""

    @staticmethod
    def _is_boilerplate_line(value: str) -> bool:
        text = value.strip()
        if not text:
            return True
        if len(text) < 2:
            return True
        for pattern in _BOILERPLATE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    @staticmethod
    def _normalize_text_lines(chunks: list[str]) -> str:
        lines: list[str] = []
        for item in chunks:
            cleaned = " ".join(str(item).split())
            if URLReviewClient._is_boilerplate_line(cleaned):
                continue
            if lines and cleaned == lines[-1]:
                continue
            if len(cleaned) > 900:
                cleaned = cleaned[:897].rstrip() + "..."
            lines.append(cleaned)
        merged = "\n".join(lines)
        if len(merged) > _MAX_EXTRACTED_CHARS:
            merged = merged[:_MAX_EXTRACTED_CHARS]
        return merged

    @staticmethod
    def _extract_title(document: lxml_html.HtmlElement) -> str:
        title_parts = [item.strip() for item in document.xpath("//title/text()") if item.strip()]
        if title_parts:
            return " ".join(title_parts)[:240]
        return "Untitled page"

    @staticmethod
    def _extract_html_text_with_fallback(raw_html: str) -> tuple[str, str]:
        title = "Untitled page"
        main_text = ""

        if ReadabilityDocument is not None:
            try:
                readable_doc = ReadabilityDocument(raw_html)
                short_title = " ".join(str(readable_doc.short_title() or "").split()).strip()
                if short_title:
                    title = short_title[:240]
                readable_html = readable_doc.summary(html_partial=True)
                readable_tree = lxml_html.fromstring(readable_html)
                readable_text_nodes = readable_tree.xpath("//text()")
                main_text = URLReviewClient._normalize_text_lines([str(node) for node in readable_text_nodes])
            except Exception:
                main_text = ""

        try:
            document = lxml_html.fromstring(raw_html)
        except Exception:
            return title, main_text

        for node in document.xpath(
            "//script|//style|//noscript|//svg|//iframe|//nav|//header|//footer|//form|//aside"
        ):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

        fallback_title = URLReviewClient._extract_title(document)
        fallback_nodes = (
            document.xpath("//main//text()")
            or document.xpath("//article//text()")
            or document.xpath("//body//text()")
            or document.xpath("//text()")
        )
        fallback_text = URLReviewClient._normalize_text_lines([str(node) for node in fallback_nodes])

        if fallback_title and title == "Untitled page":
            title = fallback_title
        if len(fallback_text) > len(main_text):
            main_text = fallback_text

        return title, main_text

    @staticmethod
    def _extract_text(text: str, content_type: str) -> tuple[str, str]:
        content_type_normalized = content_type.split(";", 1)[0].strip().lower()
        if "html" in content_type_normalized or "xhtml" in content_type_normalized:
            return URLReviewClient._extract_html_text_with_fallback(text)

        merged_plain = URLReviewClient._normalize_text_lines(text.splitlines())
        return "Plain text document", merged_plain

    async def fetch(self, *, url: str) -> ReviewedPage:
        current_url = self._validate_url(url)
        timeout = httpx.Timeout(self._timeout_seconds)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=False,
                verify=self._ssl_context,
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    current_url = self._validate_url(current_url)
                    async with client.stream("GET", current_url) as response:
                        status = int(response.status_code)
                        if status in {301, 302, 303, 307, 308}:
                            redirect_to = response.headers.get("Location", "").strip()
                            if not redirect_to:
                                raise URLReviewError("Redirect response missing Location header.")
                            current_url = urljoin(current_url, redirect_to)
                            continue
                        if status >= 400:
                            raise URLReviewError(f"Remote host returned HTTP {status}.")

                        content_type = response.headers.get("Content-Type", "").strip()
                        if not self._is_supported_content_type(content_type):
                            raise URLReviewError("Unsupported content type for review.")

                        content_length = response.headers.get("Content-Length", "").strip()
                        if content_length:
                            try:
                                if int(content_length) > self._max_bytes:
                                    raise URLReviewError("Remote response is larger than allowed size.")
                            except ValueError:
                                pass

                        buffer = bytearray()
                        async for chunk in response.aiter_bytes():
                            buffer.extend(chunk)
                            if len(buffer) > self._max_bytes:
                                raise URLReviewError("Remote response exceeded max allowed size.")

                        raw_text = self._decode_body(bytes(buffer), content_type)
                        title, page_text = self._extract_text(raw_text, content_type)
                        if not page_text.strip():
                            raise URLReviewError("Reviewed page did not yield readable text.")

                        return ReviewedPage(
                            requested_url=url,
                            final_url=current_url,
                            title=title,
                            text=page_text,
                            content_type=content_type,
                            fetched_at=datetime.now(timezone.utc).isoformat(),
                        )
        except httpx.TimeoutException as exc:
            raise URLReviewError("Request timed out while fetching URL.") from exc
        except httpx.HTTPError as exc:
            raise URLReviewError(f"Request failed while fetching URL: {exc}") from exc

        raise URLReviewError("Too many redirects while fetching URL.")
