from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import (
    EvidenceCard,
    GroundedClaim,
    GroundedResponse,
    QueryPlan,
    SavedMemoryEvent,
    URLReviewSavedItem,
)
from local_model_pro.qdrant_memory import MemoryResult
from local_model_pro.web_search import WebSearchResult


class ServerKnowledgePipelineTests(unittest.TestCase):
    def _run_chat_and_collect(
        self,
        *,
        web_assist_enabled: bool,
        grounded_mode_enabled: bool,
        prompt: str = "build a go bag list",
    ) -> tuple[list[str], list[str], list[dict[str, str]], list[dict[str, object]]]:
        from local_model_pro import server

        calls: list[str] = []
        emitted_types: list[str] = []
        streamed_messages: list[dict[str, str]] = []
        emitted_payloads: list[dict[str, object]] = []

        async def fake_build_query_plan(self, *, prompt: str, history: list[dict[str, str]], model: str) -> QueryPlan:  # type: ignore[no-untyped-def]
            _ = history
            _ = model
            calls.append("build_query_plan")
            return QueryPlan(
                reason="reason",
                meaning="meaning",
                purpose="purpose",
                db_query=f"db:{prompt}",
                web_query=f"web:{prompt}",
                fallback=False,
            )

        async def fake_search_memory(  # type: ignore[no-untyped-def]
            self,
            *,
            query: str,
            actor_id: str,
            current_session_id: str,
            query_plan: QueryPlan | None = None,
        ) -> list[MemoryResult]:
            _ = query
            _ = actor_id
            _ = current_session_id
            _ = query_plan
            calls.append("search_memory")
            return [
                MemoryResult(
                    evidence_id="mem-1",
                    insight="Generalized checklist pattern for emergency prep.",
                    score=0.92,
                    source_session="shared-1",
                    speaker="me",
                    created_at="2026-03-07T00:00:00Z",
                    actor_id="other-user",
                    pii_flag=False,
                    allow_cross_user=True,
                    source_type="insight",
                    quote_text="generalized checklist pattern",
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
            _ = query
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

        async def fake_generate_grounded_response(  # type: ignore[no-untyped-def]
            self,
            *,
            prompt: str,
            model: str,
            grounded_profile: str,
            exact_required: bool,
            evidence_cards: list[object],
        ) -> GroundedResponse:
            _ = prompt
            _ = model
            _ = grounded_profile
            _ = exact_required
            _ = evidence_cards
            calls.append("generate_grounded_response")
            return GroundedResponse(
                status="full",
                answer_text="Source: memory_same_session | Confidence: 0.91\nGrounded answer [E1].",
                claims=[
                    GroundedClaim(
                        claim_id="claim-1",
                        text="Grounded answer.",
                        evidence_ids=["E1"],
                        confidence=0.91,
                        status="grounded",
                    )
                ],
                overall_confidence=0.91,
                clarify_question="",
                note="ok",
            )

        async def fake_log(*_: object, **__: object) -> None:  # type: ignore[no-untyped-def]
            return None

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
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.generate_grounded_response",
                    new=fake_generate_grounded_response,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.log_grounded_run_start",
                    new=fake_log,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.log_grounded_evidence",
                    new=fake_log,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.log_grounded_claims",
                    new=fake_log,
                ), mock.patch(
                    "local_model_pro.knowledge_assist.KnowledgeAssistService.log_grounded_run_finish",
                    new=fake_log,
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
                                    "grounded_mode_enabled": grounded_mode_enabled,
                                    "grounded_profile": "balanced",
                                    "actor_id": "tester",
                                }
                            )
                            _ = ws.receive_json()
                            ws.send_json({"type": "chat", "prompt": prompt})

                            while True:
                                msg = ws.receive_json()
                                msg_type = str(msg.get("type", ""))
                                emitted_types.append(msg_type)
                                emitted_payloads.append(msg)
                                if msg_type == "done":
                                    break
            finally:
                temp_store.close()
                server.conversation_store = original_store

        return calls, emitted_types, streamed_messages, emitted_payloads

    def test_chat_pipeline_order_with_web_enabled(self) -> None:
        calls, emitted_types, _, _ = self._run_chat_and_collect(
            web_assist_enabled=True,
            grounded_mode_enabled=False,
        )

        # Memory retrieval is always executed before web lookup.
        self.assertEqual(calls[:3], ["build_query_plan", "search_memory", "web_search"])
        self.assertIn("query_plan", emitted_types)
        self.assertIn("memory_results", emitted_types)
        self.assertIn("web_results", emitted_types)
        self.assertIn("done", emitted_types)

    def test_chat_pipeline_order_with_web_disabled(self) -> None:
        calls, emitted_types, streamed_messages, _ = self._run_chat_and_collect(
            web_assist_enabled=False,
            grounded_mode_enabled=False,
        )

        self.assertEqual(calls[:2], ["build_query_plan", "search_memory"])
        self.assertNotIn("web_search", calls)
        self.assertIn("query_plan", emitted_types)
        self.assertIn("memory_results", emitted_types)
        self.assertNotIn("web_results", emitted_types)
        self.assertIn("done", emitted_types)

        # Privacy path: streamed context gets memory insights, not arbitrary transcript dumps.
        joined = json.dumps(streamed_messages)
        self.assertIn("Generalized checklist pattern for emergency prep.", joined)
        self.assertNotIn("raw direct transcript", joined)

    def test_grounded_chat_emits_evidence_and_grounding_status_with_web(self) -> None:
        calls, emitted_types, _, _ = self._run_chat_and_collect(
            web_assist_enabled=True,
            grounded_mode_enabled=True,
        )

        self.assertEqual(calls[:4], ["build_query_plan", "search_memory", "web_search", "generate_grounded_response"])
        self.assertIn("query_plan", emitted_types)
        self.assertIn("memory_results", emitted_types)
        self.assertIn("web_results", emitted_types)
        self.assertIn("evidence_used", emitted_types)
        self.assertIn("grounding_status", emitted_types)
        self.assertIn("done", emitted_types)

    def test_grounded_chat_without_web_still_emits_memory_and_grounding(self) -> None:
        calls, emitted_types, _, payloads = self._run_chat_and_collect(
            web_assist_enabled=False,
            grounded_mode_enabled=True,
        )

        self.assertEqual(calls[:3], ["build_query_plan", "search_memory", "generate_grounded_response"])
        self.assertNotIn("web_search", calls)
        self.assertIn("query_plan", emitted_types)
        self.assertIn("memory_results", emitted_types)
        self.assertNotIn("web_results", emitted_types)
        self.assertIn("evidence_used", emitted_types)
        self.assertIn("grounding_status", emitted_types)
        self.assertIn("done", emitted_types)

        grounding_events = [item for item in payloads if item.get("type") == "grounding_status"]
        self.assertTrue(grounding_events)
        self.assertEqual(grounding_events[-1].get("status"), "full")

    def test_save_directive_emits_memory_saved_event(self) -> None:
        calls: list[dict[str, object]] = []

        async def fake_save_direct_memory(self, **kwargs: object) -> SavedMemoryEvent:  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return SavedMemoryEvent(
                artifact_id="artifact-1",
                file_path="/tmp/session_snapshot_x.md",
                indexed_count=2,
                note="saved",
                summary="summary",
                author="Tristan Conner",
            )

        with mock.patch(
            "local_model_pro.knowledge_assist.KnowledgeAssistService.save_direct_memory",
            new=fake_save_direct_memory,
        ):
            _, emitted_types, _, payloads = self._run_chat_and_collect(
                web_assist_enabled=False,
                grounded_mode_enabled=False,
                prompt="save this for later, you are the author Tristan Conner",
            )

        self.assertTrue(calls)
        self.assertIn("memory_saved", emitted_types)
        saved_events = [item for item in payloads if item.get("type") == "memory_saved"]
        self.assertTrue(saved_events)
        self.assertEqual(saved_events[-1].get("artifact_id"), "artifact-1")
        self.assertIn("done", emitted_types)

    def test_review_intent_emits_url_review_saved(self) -> None:
        review_calls: list[dict[str, object]] = []

        async def fake_review_and_save_urls(self, **kwargs: object):  # type: ignore[no-untyped-def]
            review_calls.append(kwargs)
            return (
                [
                    URLReviewSavedItem(
                        url="https://example.com",
                        status="saved",
                        raw_file="/tmp/url_raw_x.txt",
                        meaning_file="/tmp/url_meaning_x.md",
                        artifact_id="artifact-2",
                        indexed_count=3,
                        error=None,
                        final_url="https://example.com",
                        title="Example Domain",
                        meaning="A sample page for testing.",
                        key_facts=["Example fact"],
                    )
                ],
                [
                    EvidenceCard(
                        evidence_id="ev-review-1",
                        source_type="web_review",
                        actor_scope="web",
                        label="E1",
                        content="Example Domain\\nA sample page for testing.",
                        url="https://example.com",
                        source_session=None,
                        confidence=0.72,
                        pii_flag=False,
                        used_verbatim=False,
                    )
                ],
            )

        with mock.patch(
            "local_model_pro.knowledge_assist.KnowledgeAssistService.review_and_save_urls",
            new=fake_review_and_save_urls,
        ):
            _, emitted_types, _, payloads = self._run_chat_and_collect(
                web_assist_enabled=False,
                grounded_mode_enabled=False,
                prompt="please review https://example.com and summarize",
            )

        self.assertTrue(review_calls)
        self.assertIn("url_review_saved", emitted_types)
        events = [item for item in payloads if item.get("type") == "url_review_saved"]
        self.assertTrue(events)
        self.assertIn("items", events[-1])
        self.assertIn("done", emitted_types)

    def test_plain_url_without_review_intent_does_not_trigger_review_ingest(self) -> None:
        review_calls: list[dict[str, object]] = []

        async def fake_review_and_save_urls(self, **kwargs: object):  # type: ignore[no-untyped-def]
            review_calls.append(kwargs)
            return ([], [])

        with mock.patch(
            "local_model_pro.knowledge_assist.KnowledgeAssistService.review_and_save_urls",
            new=fake_review_and_save_urls,
        ):
            _, emitted_types, _, _ = self._run_chat_and_collect(
                web_assist_enabled=False,
                grounded_mode_enabled=False,
                prompt="here is a URL https://example.com for context",
            )

        self.assertFalse(review_calls)
        self.assertNotIn("url_review_saved", emitted_types)
        self.assertIn("done", emitted_types)


if __name__ == "__main__":
    unittest.main()
