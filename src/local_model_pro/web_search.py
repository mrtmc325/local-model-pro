from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from lxml import html as lxml_html


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str


class WebSearchError(RuntimeError):
    """Raised when web search cannot return usable results."""


class WebSearchClient:
    def search(
        self,
        *,
        query: str,
        max_results: int = 5,
    ) -> list[WebSearchResult]:
        search_query = query.strip()
        if not search_query:
            raise WebSearchError("Web search query cannot be empty.")

        limit = max(1, min(max_results, 10))
        providers = [
            ("duckduckgo", self._search_via_duckduckgo_html),
            ("brave", self._search_via_brave_html),
        ]
        errors: list[str] = []
        for name, provider in providers:
            try:
                results = provider(
                    query=search_query,
                    max_results=limit,
                )
            except Exception as exc:  # pragma: no cover - network/provider errors
                errors.append(f"{name}: {exc}")
                continue
            if results:
                return results

        if errors:
            raise WebSearchError(f"Web search request failed: {'; '.join(errors)}")
        raise WebSearchError("No web search results returned.")

    @staticmethod
    def _normalize(rows: Iterable[dict[str, object]]) -> list[WebSearchResult]:
        results: list[WebSearchResult] = []
        for row in rows:
            title = str(row.get("title", "")).strip()
            url = str(row.get("href", "")).strip()
            snippet = str(row.get("body", "")).strip()
            if not url:
                continue
            if not title:
                title = url
            if len(snippet) > 420:
                snippet = f"{snippet[:417]}..."
            results.append(WebSearchResult(title=title, url=url, snippet=snippet))
        return results

    @staticmethod
    def _search_via_duckduckgo_html(*, query: str, max_results: int) -> list[WebSearchResult]:
        url = "https://duckduckgo.com/html/"
        params = {"q": query}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        response = httpx.get(
            url,
            params=params,
            headers=headers,
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()

        document = lxml_html.fromstring(response.text)
        items = document.xpath("//div[contains(@class,'result')]")
        results: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        for item in items:
            title_bits = item.xpath(".//a[contains(@class,'result__a')]//text()")
            href_bits = item.xpath(".//a[contains(@class,'result__a')]/@href")
            snippet_bits = item.xpath(
                ".//*[contains(@class,'result__snippet')]//text()"
            )
            if not href_bits:
                continue

            raw_url = href_bits[0].strip()
            parsed = urlparse(raw_url)
            if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
                uddg = parse_qs(parsed.query).get("uddg", [])
                if uddg:
                    raw_url = unquote(uddg[0])
                    parsed = urlparse(raw_url)
            if "duckduckgo.com" in parsed.netloc:
                # Skip internal tracking/ads links that do not resolve to a source page.
                continue
            if not raw_url:
                continue
            canonical = raw_url.rstrip("/")
            if canonical in seen_urls:
                continue

            title = " ".join(bit.strip() for bit in title_bits if bit.strip()) or raw_url
            snippet = " ".join(bit.strip() for bit in snippet_bits if bit.strip())
            if len(snippet) > 420:
                snippet = f"{snippet[:417]}..."

            results.append(WebSearchResult(title=title, url=raw_url, snippet=snippet))
            seen_urls.add(canonical)
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def _search_via_brave_html(*, query: str, max_results: int) -> list[WebSearchResult]:
        url = "https://search.brave.com/search"
        params = {"q": query}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        response = httpx.get(
            url,
            params=params,
            headers=headers,
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()

        document = lxml_html.fromstring(response.text)
        links = document.xpath("//a[@href]")
        results: list[WebSearchResult] = []
        seen_urls: set[str] = set()

        for link in links:
            raw_url = str(link.get("href", "")).strip()
            if not raw_url.startswith("http"):
                continue
            parsed = urlparse(raw_url)
            if "brave.com" in parsed.netloc:
                continue

            title_bits = link.xpath(".//text()")
            title = " ".join(bit.strip() for bit in title_bits if bit.strip()) or raw_url
            if len(title) > 240:
                title = f"{title[:237]}..."

            canonical = raw_url.rstrip("/")
            if canonical in seen_urls:
                continue

            results.append(
                WebSearchResult(
                    title=title,
                    url=raw_url,
                    snippet="",
                )
            )
            seen_urls.add(canonical)
            if len(results) >= max_results:
                break

        return results
