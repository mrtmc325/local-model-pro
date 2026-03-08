from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.knowledge_assist import KnowledgeAssistService


class _FakeOllama:
    async def chat(self, **_: object) -> str:
        return '{"meaning":"Session focuses on deploy readiness.","key_facts":["Author requested persistence","Conversation includes deployment checks"]}'

    async def embed(self, **_: object) -> list[float]:
        return [0.12, 0.33, 0.54]


class _CapturingMemoryIndex:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def upsert(self, **kwargs: object) -> None:
        self.calls.append(kwargs)

    async def search(self, **_: object) -> list[object]:
        return []


class DirectSaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_save_persists_snapshot_file_and_indexes_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            exports_dir = Path(tmpdir) / "exports"
            store = ConversationStore(db_path=str(db_path))
            store.upsert_session(
                session_id="sess-1",
                model="qwen2.5:7b",
                system_prompt=None,
                actor_id="tester",
            )
            store.append_turn(
                session_id="sess-1",
                speaker="me",
                content="save this for later",
                request_id="req-1",
                model="qwen2.5:7b",
                actor_id="tester",
            )

            memory_index = _CapturingMemoryIndex()
            service = KnowledgeAssistService(
                settings=Settings(memory_export_dir=str(exports_dir)),
                ollama=_FakeOllama(),  # type: ignore[arg-type]
                store=store,
                memory_index=memory_index,  # type: ignore[arg-type]
            )

            event = await service.save_direct_memory(
                session_id="sess-1",
                actor_id="tester",
                request_id="req-1",
                model="qwen2.5:7b",
                save_text="save this for later",
                author="Tristan Conner",
            )

            self.assertTrue(Path(event.file_path).exists())
            self.assertIn("session_snapshot_", Path(event.file_path).name)
            self.assertGreaterEqual(event.indexed_count, 1)
            self.assertGreaterEqual(len(memory_index.calls), 1)

            artifacts = store.list_memory_artifacts(session_id="sess-1", limit=20)
            self.assertGreaterEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0].artifact_type, "session_snapshot")
            store.close()


if __name__ == "__main__":
    unittest.main()
