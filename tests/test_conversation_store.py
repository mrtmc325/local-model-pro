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

            insight_hits = store.search_insights_by_terms(
                terms=["katie", "success"],
                actor_id="anonymous",
                current_session_id=session_id,
                include_shared=True,
                limit=10,
            )
            turn_hits = store.search_turns_by_terms(
                terms=["katie", "success"],
                actor_id="anonymous",
                current_session_id=session_id,
                include_shared=True,
                limit=10,
            )

            self.assertGreaterEqual(len(insight_hits), 1)
            self.assertGreaterEqual(len(turn_hits), 1)
            self.assertIn("Katie", insight_hits[0].insight)
            self.assertIn("katie", turn_hits[0].content.lower())
            store.close()

    def test_shared_search_respects_pii_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = ConversationStore(db_path=str(db_path))

            store.upsert_session(
                session_id="sess-a",
                model="qwen2.5:7b",
                system_prompt=None,
                actor_id="alice",
            )
            store.add_insight(
                session_id="sess-a",
                speaker="me",
                insight="Alice says Katie is her romantic partner.",
                actor_id="alice",
                pii_flag=True,
                allow_cross_user=False,
            )
            store.add_insight(
                session_id="sess-a",
                speaker="me",
                insight="Alice created a backpacking checklist for winter.",
                actor_id="alice",
                pii_flag=False,
                allow_cross_user=True,
            )

            hits_for_other_user = store.search_insights_by_terms(
                terms=["alice", "katie", "checklist"],
                actor_id="bob",
                current_session_id="sess-b",
                include_shared=True,
                limit=20,
            )

            joined = " | ".join(item.insight for item in hits_for_other_user)
            self.assertIn("backpacking checklist", joined)
            self.assertNotIn("romantic partner", joined)
            store.close()

    def test_grounded_ledger_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = ConversationStore(db_path=str(db_path))
            store.start_grounded_run(
                run_id="run-1",
                session_id="sess-1",
                actor_id="alice",
                mode="grounded",
                profile="balanced",
                prompt="what did we decide monday",
            )
            store.add_grounded_evidence(
                evidence_id="ev-1",
                run_id="run-1",
                source_type="memory_same_session",
                actor_scope="same_session",
                pii_flag=False,
                label="E1",
                content="We created script alpha on Monday.",
                url=None,
                source_session="sess-1",
                confidence=0.88,
            )
            store.add_grounded_claim(
                claim_id="claim-1",
                run_id="run-1",
                claim_text="Script alpha was created on Monday.",
                is_exact_required=True,
                support_status="grounded",
                confidence=0.88,
            )
            store.link_claim_evidence(
                claim_id="claim-1",
                evidence_id="ev-1",
                support_score=0.88,
                used_verbatim=True,
            )
            store.finish_grounded_run(run_id="run-1", status="full", note="ok")

            evidence = store.list_grounded_evidence(run_id="run-1", limit=10)
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].label, "E1")
            self.assertIn("script alpha", evidence[0].content.lower())
            store.close()

    def test_memory_artifact_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            store = ConversationStore(db_path=str(db_path))
            store.upsert_session(
                session_id="sess-artifact",
                model="qwen2.5:7b",
                system_prompt=None,
                actor_id="alice",
            )
            artifact = store.add_memory_artifact(
                artifact_id="artifact-1",
                session_id="sess-artifact",
                actor_id="alice",
                request_id="req-art",
                artifact_type="session_snapshot",
                source_url=None,
                author="Alice",
                summary="Snapshot summary",
                file_path="/tmp/snapshot.md",
                content_hash="abc123",
            )
            self.assertEqual(artifact.artifact_id, "artifact-1")
            artifacts = store.list_memory_artifacts(session_id="sess-artifact", limit=10)
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0].artifact_type, "session_snapshot")
            self.assertEqual(artifacts[0].author, "Alice")
            store.close()


if __name__ == "__main__":
    unittest.main()
