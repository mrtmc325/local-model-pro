from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx


class OllamaStreamError(RuntimeError):
    """Raised when Ollama returns an error or invalid stream payload."""


class OllamaClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def list_models(self) -> list[dict[str, Any]]:
        url = f"{self._base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise OllamaStreamError(f"Unable to reach Ollama at {self._base_url}: {exc}") from exc

        if response.status_code != 200:
            raise OllamaStreamError(
                f"Ollama error {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaStreamError("Invalid JSON payload from Ollama /api/tags") from exc

        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            raise OllamaStreamError("Unexpected /api/tags payload shape: expected 'models' list")

        models: list[dict[str, Any]] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            models.append(
                {
                    "name": name.strip(),
                    "size": item.get("size"),
                    "modified_at": item.get("modified_at"),
                    "digest": item.get("digest"),
                }
            )

        return models

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        num_ctx: int,
        think: bool | str | None = None,
    ) -> AsyncIterator[str]:
        attempt_think_values: list[bool | str | None] = [think]
        if think is not None:
            # Some Ollama models reject the `think` field; retry once without it.
            attempt_think_values.append(None)

        last_error: OllamaStreamError | None = None
        for attempt_index, attempt_think in enumerate(attempt_think_values):
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_ctx": num_ctx,
                },
            }
            if attempt_think is not None:
                payload["think"] = attempt_think

            emitted_any = False
            try:
                async for chunk in self._stream_chat_once(payload):
                    emitted_any = True
                    yield chunk
                return
            except OllamaStreamError as exc:
                last_error = exc
                should_retry_without_think = (
                    attempt_index == 0
                    and attempt_think is not None
                    and not emitted_any
                    and self._is_think_unsupported_error(str(exc))
                )
                if should_retry_without_think:
                    continue
                raise

        if last_error is not None:
            raise last_error

    @staticmethod
    def _is_think_unsupported_error(error_text: str) -> bool:
        lowered = error_text.lower()
        return (
            "does not support thinking" in lowered
            or "unknown field \"think\"" in lowered
            or "invalid field \"think\"" in lowered
        )

    async def _stream_chat_once(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        url = f"{self._base_url}/api/chat"
        thinking_open = False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise OllamaStreamError(
                            f"Ollama error {response.status_code}: {error_text.decode('utf-8', errors='ignore')}"
                        )

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaStreamError(f"Invalid Ollama stream chunk: {line}") from exc

                        if "error" in item:
                            raise OllamaStreamError(str(item["error"]))

                        message = item.get("message", {})
                        thinking = message.get("thinking", "")
                        if thinking:
                            if not thinking_open:
                                thinking_open = True
                                yield "<think>"
                            yield str(thinking)

                        content = message.get("content", "")
                        if content:
                            if thinking_open:
                                thinking_open = False
                                yield "</think>"
                            yield str(content)

                        if item.get("done", False):
                            if thinking_open:
                                thinking_open = False
                                yield "</think>"
                            break
        except httpx.HTTPError as exc:
            raise OllamaStreamError(f"Unable to reach Ollama at {self._base_url}: {exc}") from exc

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        num_ctx: int,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        url = f"{self._base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise OllamaStreamError(f"Unable to reach Ollama at {self._base_url}: {exc}") from exc
        if response.status_code != 200:
            raise OllamaStreamError(
                f"Ollama error {response.status_code}: {response.text[:500]}"
            )

        try:
            item = response.json()
        except ValueError as exc:
            raise OllamaStreamError("Invalid JSON payload from Ollama /api/chat") from exc

        if not isinstance(item, dict):
            raise OllamaStreamError("Unexpected /api/chat payload shape.")
        if "error" in item:
            raise OllamaStreamError(str(item["error"]))

        message = item.get("message", {})
        if not isinstance(message, dict):
            raise OllamaStreamError("Missing 'message' object in /api/chat response.")
        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaStreamError("Missing string 'message.content' in /api/chat response.")
        return content
