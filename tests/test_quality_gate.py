from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import patch

# The production dependency is installed by requirements.txt. Keep these unit tests
# runnable in a minimal checkout where only pydantic is present.
if "dotenv" not in sys.modules:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules["dotenv"] = dotenv

from src import llm
from src.schema import Opportunity, OpportunityDecision, OpportunityReview, SourceItem


def opportunity(**overrides) -> Opportunity:
    values = {
        "summary": "Staff copy order IDs between systems to resolve failed shipments.",
        "category": "small_business",
        "evidence": "Every morning we copy failed order IDs into the carrier portal.",
        "current_workaround": "Copy IDs into the carrier portal.",
        "manual_steps": ["Find failed orders", "Copy each order ID"],
        "user_role": "operations staff",
        "buyer_role": "operations manager",
        "source_ids": ["hn-1"],
        "pain": 4,
        "frequency": 5,
        "buildability": 4,
        "market_signal": 4,
        "personal_interest": 3,
        "composite": 4.1,
    }
    values.update(overrides)
    return Opportunity(**values)


class QualityGateTests(unittest.TestCase):
    def test_invalid_source_ids_are_removed_and_ungrounded_leads_are_rejected(self):
        valid = opportunity(source_ids=["hn-1", "invented-99"])
        invalid = opportunity(summary="Unsupported claim", source_ids=["invented-100"])
        sources = [SourceItem(id="hn-1", source="hackernews", title="A real post")]

        kept, rejected = llm._normalize_source_ids([valid, invalid], sources)

        self.assertEqual(["hn-1"], kept[0].source_ids)
        self.assertEqual(3, kept[0].frequency)
        self.assertEqual([invalid], rejected)

    def test_critic_sees_original_source_and_rejects_vendor_feature_and_anecdote(self):
        candidates = [
            opportunity(
                summary="DeepSeek lacks text-to-speech and speech-to-text.",
                category="ai_agents",
                evidence="DeepSeek lacks several accessibility features.",
                current_workaround="",
                manual_steps=[],
                user_role="AI users",
                buyer_role="AI product managers",
                source_ids=["github-0-1"],
            ),
            opportunity(
                summary="Laptop users experience neck and back pain.",
                category="health",
                evidence="Ever since I got a laptop I've had recurring neck pain.",
                user_role="Laptop users",
                buyer_role="",
                source_ids=["hn-2"],
            ),
        ]
        sources = [
            SourceItem(
                id="github-0-1",
                source="github",
                title="Add voice input and output",
                text="Please add voice features to DeepSeek.",
            ),
            SourceItem(
                id="hn-2",
                source="hackernews",
                title="Laptop ergonomics",
                text="I use a stand and external keyboard when I remember.",
            ),
        ]
        review = OpportunityReview(
            decisions=[
                OpportunityDecision(index=0, keep=False, reason="vendor-owned feature"),
                OpportunityDecision(index=1, keep=False, reason="single physical anecdote"),
            ]
        )

        with patch.object(llm.config, "ENABLE_OPPORTUNITY_CRITIC", True), patch.object(
            llm, "_parse", return_value=review
        ) as parse:
            kept = llm._review_opportunities(candidates, sources)

        self.assertEqual([], kept)
        payload = parse.call_args.args[1]
        rendered = json.loads(payload.split("\n", 1)[1])
        self.assertEqual("Please add voice features to DeepSeek.", rendered[0]["original_sources"][0]["excerpt"])
        self.assertEqual("I use a stand and external keyboard when I remember.", rendered[1]["original_sources"][0]["excerpt"])

    def test_missing_critic_decision_fails_closed(self):
        candidate = opportunity()
        source = SourceItem(id="hn-1", source="hackernews", title="Operations pain")
        with patch.object(llm.config, "ENABLE_OPPORTUNITY_CRITIC", True), patch.object(
            llm, "_parse", return_value=OpportunityReview(decisions=[])
        ):
            self.assertEqual([], llm._review_opportunities([candidate], [source]))

    def test_critic_error_fails_closed(self):
        candidate = opportunity()
        source = SourceItem(id="hn-1", source="hackernews", title="Operations pain")
        with patch.object(llm.config, "ENABLE_OPPORTUNITY_CRITIC", True), patch.object(
            llm, "_parse", side_effect=RuntimeError("provider unavailable")
        ):
            self.assertEqual([], llm._review_opportunities([candidate], [source]))


if __name__ == "__main__":
    unittest.main()
