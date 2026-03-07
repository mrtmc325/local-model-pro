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

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        num_ctx: int,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        url = f"{self._base_url}/api/chat"
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
                    content = message.get("content", "")
                    if content:
                        yield content

                    if item.get("done", False):
                        break

