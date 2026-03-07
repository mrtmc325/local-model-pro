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
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url)

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
