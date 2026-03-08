from __future__ import annotations

import unittest
from datetime import datetime, timezone

from local_model_pro.config import Settings
from local_model_pro.knowledge_assist import RecursivePlanner


class _FakeOllama:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def chat(self, **_: object) -> str:
        if not self._responses:
            return ""
        return self._responses.pop(0)


class RecursivePlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_when_first_pass_is_invalid_json(self) -> None:
        settings = Settings(knowledge_recursion_passes=3)
        planner = RecursivePlanner(settings=settings, ollama=_FakeOllama(["not json"]))

        plan = await planner.build_plan(
            prompt="Need a quick earthquake prep checklist",
            history=[],
            model="qwen2.5:7b",
        )

        self.assertTrue(plan.fallback)
        self.assertEqual(plan.db_query, "Need a quick earthquake prep checklist")
        self.assertEqual(plan.web_query, "Need a quick earthquake prep checklist")

    async def test_three_pass_plan_uses_recursive_outputs(self) -> None:
        settings = Settings(knowledge_recursion_passes=3)
        planner = RecursivePlanner(
            settings=settings,
            ollama=_FakeOllama(
                [
                    '{"reason":"Safety planning","meaning":"User wants go-bag details","purpose":"Actionable checklist"}',
                    '{"db_query":"earthquake go bag essentials and constraints","web_query":"latest FEMA earthquake go bag checklist"}',
                    '{"reason":"Safety planning","meaning":"Preparedness list for earthquake response","purpose":"Deliver concise actionable steps","db_query":"earthquake preparedness go-bag essentials","web_query":"FEMA earthquake emergency kit checklist 2026"}',
                ]
            ),
        )

        plan = await planner.build_plan(
            prompt="what do I pack for an earthquake go bag?",
            history=[],
            model="qwen2.5:7b",
        )

        self.assertFalse(plan.fallback)
        self.assertEqual(plan.reason, "Safety planning")
        self.assertEqual(plan.meaning, "Preparedness list for earthquake response")
        self.assertEqual(plan.purpose, "Deliver concise actionable steps")
        self.assertEqual(plan.db_query, "earthquake preparedness go-bag essentials")
        self.assertEqual(plan.web_query, "FEMA earthquake emergency kit checklist 2026")

    async def test_sql_like_query_is_sanitized_to_natural_language(self) -> None:
        settings = Settings(knowledge_recursion_passes=2)
        planner = RecursivePlanner(
            settings=settings,
            ollama=_FakeOllama(
                [
                    '{"reason":"Lookup prior memory","meaning":"Find statement about operator and Katie","purpose":"Recover context from memory"}',
                    "{\"db_query\":\"SELECT * FROM memories WHERE name = 'Katie'\",\"web_query\":\"SELECT * FROM memories WHERE name = 'Katie'\"}",
                ]
            ),
        )

        plan = await planner.build_plan(
            prompt="what did my operator say about katie",
            history=[],
            model="qwen2.5:7b",
        )

        self.assertNotIn("SELECT", plan.db_query.upper())
        self.assertNotIn("SELECT", plan.web_query.upper())
        self.assertIn("Find statement", plan.db_query)

    async def test_this_year_prompt_is_normalized_to_current_year(self) -> None:
        settings = Settings(knowledge_recursion_passes=2)
        planner = RecursivePlanner(
            settings=settings,
            ollama=_FakeOllama(
                [
                    '{"reason":"recency request","meaning":"current-year events","purpose":"find current-year events"}',
                    '{"db_query":"what happened between us and iran in 2023","web_query":"recent events us iran 2023"}',
                ]
            ),
        )

        plan = await planner.build_plan(
            prompt="what happened between US and Iran this year?",
            history=[],
            model="qwen2.5:7b",
        )

        current_year = str(datetime.now(timezone.utc).year)
        self.assertIn(current_year, plan.db_query)
        self.assertIn(current_year, plan.web_query)
        self.assertNotIn("2023", plan.db_query)
        self.assertNotIn("2023", plan.web_query)


if __name__ == "__main__":
    unittest.main()
