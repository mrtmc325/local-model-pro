from __future__ import annotations

import unittest

from local_model_pro.ingestion_intents import parse_prompt_ingestion_intent


class IngestionIntentTests(unittest.TestCase):
    def test_save_directive_extracts_author_and_text(self) -> None:
        prompt = "save this for later, you are the author Tristan Conner, network baseline changed"
        intent = parse_prompt_ingestion_intent(prompt)

        self.assertTrue(intent.save_requested)
        self.assertEqual(intent.author, "Tristan Conner")
        self.assertIn("network baseline changed", intent.save_text)

    def test_non_directive_does_not_trigger_save(self) -> None:
        prompt = "Can you explain how memory retrieval works?"
        intent = parse_prompt_ingestion_intent(prompt)

        self.assertFalse(intent.save_requested)
        self.assertEqual(intent.save_text, "")
        self.assertIsNone(intent.author)

    def test_url_review_requires_review_verb(self) -> None:
        with_review = parse_prompt_ingestion_intent("review https://example.com right now")
        without_review = parse_prompt_ingestion_intent("here is a url https://example.com")

        self.assertTrue(with_review.review_requested)
        self.assertEqual(with_review.review_urls, ["https://example.com"])
        self.assertFalse(without_review.review_requested)


if __name__ == "__main__":
    unittest.main()
