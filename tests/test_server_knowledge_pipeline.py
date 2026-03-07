from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import QueryPlan
from local_model_pro.qdrant_memory import MemoryResult
from local_model_pro.web_search import WebSearchResult


class ServerKnowledgePipelineTests(unittest.TestCase):
    def _run_chat_and_collect(
        self,
        *,
        web_assist_enabled: bool,
    ) -> tuple[list[str], list[str], list[dict[str, str]]]:
        from local_model_pro import server

        calls: list[str] = []
        emitted_types: list[str] = []
        streamed_messages: list[dict[str, str]] = []

        async def fake_build_query_plan(self, *, prompt: str, history: list[dict[str, str]], model: str) -> QueryPlan:  # type: ignore[no-untyped-def]
            calls.append("build_query_plan")
            return QueryPlan(
                reason="reason",
                meaning="meaning",
                purpose="purpose",
                db_query=f"db:{prompt}",
                web_query=f"web:{prompt}",
                fallback=False,
            )

        async def fake_search_memory(self, *, query: str, query_plan: QueryPlan | None = None) -> list[MemoryResult]:  # type: ignore[no-untyped-def]
            _ = query_plan
            calls.append("search_memory")
            return [
                MemoryResult(
                    insight="Generalized checklist pattern for emergency prep.",
                    score=0.92,
                    source_session="shared-1",
                    speaker="me",
                    created_at="2026-03-07T00:00:00Z",
                )
            ]

        async def fake_save_session(self, **_: object) -> None:  # type: ignore[no-untyped-def]
            return None

        async def fake_save_turn(self, **_: object) -> int:  # type: ignore[no-untyped-def]
            return 1

        async def fake_index_turn_insights(self, **_: object) -> None:  # type: ignore[no-untyped-def]
            return None

        async def fake_run_web_search(web_search: object, *, query: str, max_results: int) -> list[WebSearchResult]:  # type: ignore[no-untyped-def]
            _ = web_search
            _ = max_results
            calls.append("web_search")
            return [
                WebSearchResult(
                    title="Ready.gov kit",
                    url="https://www.ready.gov/kit",
                    snippet="Emergency supply checklist.",
                )
            ]

        async def fake_stream_chat(self, *, model: str, messages: list[dict[str, str]], temperature: float, num_ctx: int):  # type: ignore[no-untyped-def]
            _ = model
            _ = temperature
            _ = num_ctx
            streamed_messages.extend(messages)
            yield "ok"

        with tempfile.TemporaryDirectory() as tmpdir:
            original_store = server.conversation_store
            temp_store = ConversationStore(db_path=str(Path(tmpdir) / "test.db"))
            server.conversation_store = temp_store
            try:
                with mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.build_query_plan",
                    new=fake_build_query_plan,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.search_memory",
                    new=fake_search_memory,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.save_session",
                    new=fake_save_session,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.save_turn",
                    new=fake_save_turn,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.index_turn_insights",
                    new=fake_index_turn_insights,
                ), mock.patch(
                    "local_model_pro.server._run_web_search",
                    new=fake_run_web_search,
                ), mock.patch(
                    "local_model_pro.ollama_client.OllamaClient.stream_chat",
                    new=fake_stream_chat,
                ):
                    with TestClient(server.app) as client:
                        with client.websocket_connect("/ws/chat") as ws:
                            _ = ws.receive_json()
                            _ = ws.receive_json()
                            ws.send_json(
                                {
                                    "type": "hello",
                                    "model": "qwen2.5:7b",
                                    "knowledge_assist_enabled": True,
                                    "web_assist_enabled": web_assist_enabled,
                                }
                            )
                            _ = ws.receive_json()
                            ws.send_json({"type": "chat", "prompt": "build a go bag list"})

                            while True:
                                msg = ws.receive_json()
                                msg_type = str(msg.get("type", ""))
                                emitted_types.append(msg_type)
                                if msg_type == "done":
                                    break
            finally:
                temp_store.close()
                server.conversation_store = original_store

        return calls, emitted_types, streamed_messages

    def test_chat_pipeline_order_with_web_enabled(self) -> None:
        calls, emitted_types, _ = self._run_chat_and_collect(web_assist_enabled=True)

        # Memory retrieval is always executed before web lookup.
        self.assertEqual(calls[:3], ["build_query_plan", "search_memory", "web_search"])
        self.assertIn("query_plan", emitted_types)
        self.assertIn("memory_results", emitted_types)
        self.assertIn("web_results", emitted_types)
        self.assertIn("done", emitted_types)

    def test_chat_pipeline_order_with_web_disabled(self) -> None:
        calls, emitted_types, streamed_messages = self._run_chat_and_collect(web_assist_enabled=False)

        self.assertEqual(calls[:2], ["build_query_plan", "search_memory"])
        self.assertNotIn("web_search", calls)
        self.assertIn("query_plan", emitted_types)
        self.assertIn("memory_results", emitted_types)
        self.assertNotIn("web_results", emitted_types)
        self.assertIn("done", emitted_types)

        # Privacy policy: generation context receives abstracted insights, not raw transcript dumps.
        joined = json.dumps(streamed_messages)
        self.assertIn("Generalized checklist pattern for emergency prep.", joined)
        self.assertNotIn("raw direct transcript", joined)


if __name__ == "__main__":
    unittest.main()
