from __future__ import annotations

import unittest

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import EvidenceCard, KnowledgeAssistService


class _FakeOllama:
    def __init__(self, response: str) -> None:
        self._response = response

    async def chat(self, **_: object) -> str:
        return self._response

    async def embed(self, **_: object) -> list[float]:
        return [0.1, 0.2, 0.3]


class _NoopMemoryIndex:
    async def upsert(self, **_: object) -> None:
        return None

    async def search(self, **_: object) -> list[object]:
        return []


class GroundedModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_request_returns_insufficient_on_conflicting_evidence(self) -> None:
        store = ConversationStore(db_path=":memory:")
        service = KnowledgeAssistService(
            settings=Settings(),
            ollama=_FakeOllama('{"answer":"Project had tasks Monday.","note":"ok"}'),  # type: ignore[arg-type]
            store=store,
            memory_index=_NoopMemoryIndex(),  # type: ignore[arg-type]
        )
        cards = [
            EvidenceCard(
                evidence_id="ev-1",
                source_type="memory_same_session",
                actor_scope="same_session",
                label="E1",
                content="Project had 3 tasks on Monday.",
                url=None,
                source_session="sess-1",
                confidence=0.92,
                pii_flag=False,
                used_verbatim=True,
            ),
            EvidenceCard(
                evidence_id="ev-2",
                source_type="memory_same_session",
                actor_scope="same_session",
                label="E2",
                content="Project had 5 tasks on Monday.",
                url=None,
                source_session="sess-1",
                confidence=0.90,
                pii_flag=False,
                used_verbatim=True,
            ),
        ]

        result = await service.generate_grounded_response(
            prompt="How many tasks did the project have on Monday?",
            model="qwen2.5:7b",
            grounded_profile="strict",
            exact_required=True,
            evidence_cards=cards,
            reasoning_mode="debug",
        )

        self.assertEqual(result.status, "insufficient")
        self.assertTrue(result.clarify_question)
        self.assertIn("unsupported or conflicting", result.note.lower())
        self.assertIn("Used 2 evidence cards", result.reasoning_text)
        self.assertIn("status=insufficient", result.debug_text)
        self.assertIn("evidence_labels=['E1', 'E2']", result.debug_text)
        store.close()

    async def test_grounded_response_appends_claims_without_sources_footer(self) -> None:
        store = ConversationStore(db_path=":memory:")
        service = KnowledgeAssistService(
            settings=Settings(),
            ollama=_FakeOllama('{"answer":"Use checklist alpha [E1].","note":"ok"}'),  # type: ignore[arg-type]
            store=store,
            memory_index=_NoopMemoryIndex(),  # type: ignore[arg-type]
        )
        cards = [
            EvidenceCard(
                evidence_id="ev-1",
                source_type="memory_same_session",
                actor_scope="same_session",
                label="E1",
                content="Checklist alpha includes water, radio, and first aid.",
                url=None,
                source_session="sess-1",
                confidence=0.91,
                pii_flag=False,
                used_verbatim=True,
            )
        ]

        result = await service.generate_grounded_response(
            prompt="What should I include in checklist alpha?",
            model="qwen2.5:7b",
            grounded_profile="balanced",
            exact_required=False,
            evidence_cards=cards,
        )

        self.assertNotIn("Source:", result.answer_text)
        self.assertIn("Claim confidence:", result.answer_text)
        self.assertNotIn("Sources:", result.answer_text)
        self.assertNotIn("[E1]", result.answer_text)
        self.assertIn(result.status, {"full", "partial"})
        self.assertEqual(result.reasoning_text, "")
        self.assertEqual(result.debug_text, "")
        store.close()

    async def test_no_memory_hit_still_generates_reasoning_summary_when_enabled(self) -> None:
        store = ConversationStore(db_path=":memory:")
        service = KnowledgeAssistService(
            settings=Settings(),
            ollama=_FakeOllama('{"answer":"No evidence.","note":"ok"}'),  # type: ignore[arg-type]
            store=store,
            memory_index=_NoopMemoryIndex(),  # type: ignore[arg-type]
        )

        result = await service.generate_grounded_response(
            prompt="What did we decide yesterday?",
            model="qwen2.5:7b",
            grounded_profile="balanced",
            exact_required=False,
            evidence_cards=[],
            reasoning_mode="summary",
        )

        self.assertEqual(result.status, "insufficient")
        self.assertIn("No evidence available", result.note)
        self.assertIn("Used 0 evidence cards", result.reasoning_text)
        self.assertEqual(result.debug_text, "")
        store.close()


if __name__ == "__main__":
    unittest.main()
