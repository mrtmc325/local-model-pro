from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import KnowledgeAssistService, QueryPlan
from local_model_pro.ollama_client import OllamaStreamError


class _EmbedFailingOllama:
    async def chat(self, **_: object) -> str:
        return ""

    async def embed(self, **_: object) -> list[float]:
        raise OllamaStreamError("embedding unavailable")


class _NoopMemoryIndex:
    async def upsert(self, **_: object) -> None:
        return None

    async def search(self, **_: object) -> list[object]:
        return []


class MemoryLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_lexical_fallback_uses_expanded_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversationStore(db_path=str(Path(tmpdir) / "history.db"))
            session_id = "shared-memory-1"
            store.upsert_session(
                session_id=session_id,
                model="qwen2.5:7b",
                system_prompt=None,
                actor_id="tester",
            )
            store.add_insight(
                session_id=session_id,
                speaker="me",
                insight="Operator described Katie as central to success and motivation.",
                actor_id="tester",
            )

            service = KnowledgeAssistService(
                settings=Settings(knowledge_memory_top_k=5, knowledge_memory_score_threshold=0.2),
                ollama=_EmbedFailingOllama(),  # type: ignore[arg-type]
                store=store,
                memory_index=_NoopMemoryIndex(),  # type: ignore[arg-type]
            )

            plan = QueryPlan(
                reason="recover operator context",
                meaning="find what operator said about Katie",
                purpose="support follow-up reasoning",
                db_query="what did operator say",
                web_query="what did operator say about Katie",
                fallback=False,
            )
            results = await service.search_memory(
                query=plan.db_query,
                actor_id="tester",
                current_session_id=session_id,
                query_plan=plan,
            )

            self.assertGreaterEqual(len(results), 1)
            self.assertIn("Katie", results[0].insight)
            store.close()


if __name__ == "__main__":
    unittest.main()
