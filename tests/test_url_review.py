from __future__ import annotations

import socket
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest import mock

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import KnowledgeAssistService
from local_model_pro.url_review import ReviewedPage, URLReviewClient, URLReviewError


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

    async def test_review_web_results_for_context_success_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            service = await self._build_service(tmpdir)
            service._url_review_client.fetch = mock.AsyncMock(  # type: ignore[attr-defined]
                return_value=ReviewedPage(
                    requested_url="https://example.com",
                    final_url="https://example.com",
                    title="Example Domain",
                    text="Example body text for reviewed web context.",
                    content_type="text/html",
                    fetched_at="2026-03-07T00:00:00Z",
                )
            )

            items, cards = await service.review_web_results_for_context(
                model="qwen2.5:7b",
                web_results=[{"url": "https://example.com", "title": "Example Domain", "snippet": "Example snippet"}],
                max_urls=1,
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, "saved")
            self.assertIsNone(items[0].artifact_id)
            self.assertIsNone(items[0].raw_file)
            self.assertIsNone(items[0].meaning_file)
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0].source_type, "web_review")
            self.assertFalse(export_dir.exists())

    async def test_review_web_results_for_context_handles_fetch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = await self._build_service(tmpdir)
            service._url_review_client.fetch = mock.AsyncMock(  # type: ignore[attr-defined]
                side_effect=URLReviewError("request timed out")
            )

            items, cards = await service.review_web_results_for_context(
                model="qwen2.5:7b",
                web_results=[{"url": "https://example.com"}],
                max_urls=1,
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, "failed")
            self.assertIn("timed out", str(items[0].error))
            self.assertEqual(cards, [])

    async def test_review_web_results_for_context_summary_timeout_uses_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = await self._build_service(tmpdir)
            service._url_review_client.fetch = mock.AsyncMock(  # type: ignore[attr-defined]
                return_value=ReviewedPage(
                    requested_url="https://example.com",
                    final_url="https://example.com",
                    title="Example Domain",
                    text="Fallback content line one.\nFallback content line two.",
                    content_type="text/html",
                    fetched_at="2026-03-07T00:00:00Z",
                )
            )

            async def fake_summarize(*, page: ReviewedPage, model: str):  # type: ignore[no-untyped-def]
                _ = page
                _ = model
                raise asyncio.TimeoutError()

            service._summarize_reviewed_page = fake_summarize  # type: ignore[method-assign,assignment]

            items, cards = await service.review_web_results_for_context(
                model="qwen2.5:7b",
                web_results=[{"url": "https://example.com"}],
                max_urls=1,
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].status, "saved")
            self.assertTrue(items[0].meaning)
            self.assertEqual(len(cards), 1)
            self.assertIn("Example Domain", cards[0].content)


if __name__ == "__main__":
    unittest.main()
