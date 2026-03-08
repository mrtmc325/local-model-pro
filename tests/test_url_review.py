from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import KnowledgeAssistService
from local_model_pro.url_review import URLReviewClient, URLReviewError


class _FakeOllama:
    async def chat(self, **_: object) -> str:
        return '{"meaning":"summary","key_facts":["fact one"]}'

    async def embed(self, **_: object) -> list[float]:
        return [0.1, 0.2, 0.3]


class _NoopMemoryIndex:
    async def upsert(self, **_: object) -> None:
        return None

    async def search(self, **_: object) -> list[object]:
        return []


class URLReviewClientValidationTests(unittest.TestCase):
    def test_validate_url_blocks_localhost_and_private_ip(self) -> None:
        with self.assertRaises(URLReviewError):
            URLReviewClient._validate_url("http://localhost/test")
        with self.assertRaises(URLReviewError):
            URLReviewClient._validate_url("http://192.168.1.1/test")

    @mock.patch("local_model_pro.url_review.socket.getaddrinfo")
    def test_validate_url_allows_public_dns_host(self, mocked_getaddrinfo: mock.Mock) -> None:
        mocked_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ]

        validated = URLReviewClient._validate_url("https://example.com/path")
        self.assertEqual(validated, "https://example.com/path")


class URLReviewFailureModeTests(unittest.IsolatedAsyncioTestCase):
    async def _build_service(self, tmpdir: str) -> KnowledgeAssistService:
        store = ConversationStore(db_path=str(Path(tmpdir) / "history.db"))
        store.upsert_session(
            session_id="sess-1",
            model="qwen2.5:7b",
            system_prompt=None,
            actor_id="tester",
        )
        return KnowledgeAssistService(
            settings=Settings(memory_export_dir=str(Path(tmpdir) / "exports")),
            ollama=_FakeOllama(),  # type: ignore[arg-type]
            store=store,
            memory_index=_NoopMemoryIndex(),  # type: ignore[arg-type]
        )

    async def test_url_review_failure_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = await self._build_service(tmpdir)
            service._url_review_client.fetch = mock.AsyncMock(  # type: ignore[attr-defined]
                side_effect=URLReviewError("request timed out")
            )

            items, cards = await service.review_and_save_urls(
                session_id="sess-1",
                actor_id="tester",
                request_id="req-1",
                model="qwen2.5:7b",
                urls=["https://example.com"],
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, "failed")
            self.assertIn("timed out", str(items[0].error))
            self.assertEqual(cards, [])

    async def test_url_review_failure_on_invalid_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = await self._build_service(tmpdir)
            service._url_review_client.fetch = mock.AsyncMock(  # type: ignore[attr-defined]
                side_effect=URLReviewError("Unsupported content type for review.")
            )

            items, _ = await service.review_and_save_urls(
                session_id="sess-1",
                actor_id="tester",
                request_id="req-2",
                model="qwen2.5:7b",
                urls=["https://example.com/file.pdf"],
            )

            self.assertEqual(items[0].status, "failed")
            self.assertIn("Unsupported content type", str(items[0].error))

    async def test_url_review_failure_on_oversized_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = await self._build_service(tmpdir)
            service._url_review_client.fetch = mock.AsyncMock(  # type: ignore[attr-defined]
                side_effect=URLReviewError("Remote response exceeded max allowed size.")
            )

            items, _ = await service.review_and_save_urls(
                session_id="sess-1",
                actor_id="tester",
                request_id="req-3",
                model="qwen2.5:7b",
                urls=["https://example.com/big"],
            )

            self.assertEqual(items[0].status, "failed")
            self.assertIn("max allowed size", str(items[0].error))


if __name__ == "__main__":
    unittest.main()
