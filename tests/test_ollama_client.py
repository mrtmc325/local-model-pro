from __future__ import annotations

import json
import unittest
from unittest import mock

from local_model_pro.ollama_client import OllamaClient, OllamaStreamError


class _FakeResponse:
    def __init__(self, *, status_code: int, lines: list[str] | None = None, body: bytes = b"") -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._body = body

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):  # type: ignore[override]
        for line in self._lines:
            yield line


class _FakeStreamContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeAsyncClient:
    scripted_responses: list[_FakeResponse] = []
    request_payloads: list[dict[str, object]] = []

    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def stream(self, method: str, url: str, json: dict[str, object]):  # type: ignore[override]
        _ = (method, url)
        _FakeAsyncClient.request_payloads.append(dict(json))
        if not _FakeAsyncClient.scripted_responses:
            raise AssertionError("No scripted response available for stream call.")
        return _FakeStreamContext(_FakeAsyncClient.scripted_responses.pop(0))


class OllamaClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeAsyncClient.scripted_responses = []
        _FakeAsyncClient.request_payloads = []

    async def test_stream_chat_retries_without_think_when_unsupported(self) -> None:
        _FakeAsyncClient.scripted_responses = [
            _FakeResponse(
                status_code=400,
                body=b'{"error":"\\"qwen2.5:7b\\" does not support thinking"}',
            ),
            _FakeResponse(
                status_code=200,
                lines=[
                    json.dumps({"message": {"content": "ok"}, "done": False}),
                    json.dumps({"done": True}),
                ],
            ),
        ]
        client = OllamaClient(base_url="http://unit-test")

        with mock.patch("local_model_pro.ollama_client.httpx.AsyncClient", new=_FakeAsyncClient):
            chunks: list[str] = []
            async for chunk in client.stream_chat(
                model="qwen2.5:7b",
                messages=[{"role": "user", "content": "test"}],
                temperature=0.2,
                num_ctx=1024,
                think=True,
            ):
                chunks.append(chunk)

        self.assertEqual("".join(chunks), "ok")
        self.assertEqual(len(_FakeAsyncClient.request_payloads), 2)
        self.assertEqual(_FakeAsyncClient.request_payloads[0].get("think"), True)
        self.assertNotIn("think", _FakeAsyncClient.request_payloads[1])

    async def test_stream_chat_does_not_retry_for_unrelated_error(self) -> None:
        _FakeAsyncClient.scripted_responses = [
            _FakeResponse(status_code=400, body=b'{"error":"bad request"}'),
        ]
        client = OllamaClient(base_url="http://unit-test")

        with mock.patch("local_model_pro.ollama_client.httpx.AsyncClient", new=_FakeAsyncClient):
            with self.assertRaises(OllamaStreamError):
                async for _ in client.stream_chat(
                    model="qwen2.5:7b",
                    messages=[{"role": "user", "content": "test"}],
                    temperature=0.2,
                    num_ctx=1024,
                    think=True,
                ):
                    pass

        self.assertEqual(len(_FakeAsyncClient.request_payloads), 1)
        self.assertEqual(_FakeAsyncClient.request_payloads[0].get("think"), True)
