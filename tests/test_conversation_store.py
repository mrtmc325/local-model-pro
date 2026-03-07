from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_model_pro.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_persists_me_you_turns_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            session_id = "session-1"

            store_1 = ConversationStore(db_path=str(db_path))
            store_1.upsert_session(session_id=session_id, model="qwen2.5:7b", system_prompt=None)
            store_1.append_turn(
                session_id=session_id,
                speaker="me",
                content="we built a script last monday",
                request_id="req-1",
                model="qwen2.5:7b",
            )
            store_1.append_turn(
                session_id=session_id,
                speaker="you",
                content="the script should parse CSV and export JSON",
                request_id="req-1",
                model="qwen2.5:7b",
            )
            store_1.close()

            store_2 = ConversationStore(db_path=str(db_path))
            turns = store_2.list_turns(session_id=session_id, limit=10)

            self.assertEqual(len(turns), 2)
            self.assertEqual(turns[0]["speaker"], "me")
            self.assertEqual(turns[1]["speaker"], "you")
            self.assertIn("script", turns[0]["content"])
            store_2.close()

    def test_keyword_search_hits_insights_and_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            session_id = "session-2"
            store = ConversationStore(db_path=str(db_path))
            store.upsert_session(session_id=session_id, model="qwen2.5:7b", system_prompt=None)
            store.append_turn(
                session_id=session_id,
                speaker="me",
                content="my operator loves Katie and says she is key to success",
                request_id="req-2",
                model="qwen2.5:7b",
            )
            store.add_insight(
                session_id=session_id,
                speaker="me",
                insight="Operator identified Katie as a key motivation for success.",
            )

            insight_hits = store.search_insights_by_terms(terms=["katie", "success"], limit=10)
            turn_hits = store.search_turns_by_terms(terms=["katie", "success"], limit=10)

            self.assertGreaterEqual(len(insight_hits), 1)
            self.assertGreaterEqual(len(turn_hits), 1)
            self.assertIn("Katie", insight_hits[0].insight)
            self.assertIn("katie", turn_hits[0].content.lower())
            store.close()


if __name__ == "__main__":
    unittest.main()
