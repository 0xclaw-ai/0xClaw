"""Tests for orchestration.router — SkillRouter and keyword matching."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "0xclaw"))

from orchestration.router import KEYWORD_MAP, PHASE_ORDER, SkillRouter


class KeywordMatchTests(unittest.TestCase):
    """Test that known keywords route to the correct phase."""

    def setUp(self) -> None:
        self.router = SkillRouter()

    def test_exact_english_keyword_per_phase(self) -> None:
        test_cases = {
            "research": "research",
            "idea": "brainstorm",
            "selection": "select idea",
            "planning": "plan architecture",
            "coding": "start coding",
            "testing": "run tests",
            "doc": "prepare docs",
        }
        for expected_phase, keyword in test_cases.items():
            decision = self.router.route(keyword)
            self.assertEqual(
                decision.phase, expected_phase,
                f"'{keyword}' should route to {expected_phase}, got {decision.phase}",
            )

    def test_chinese_keyword_research(self) -> None:
        decision = self.router.route("调研")
        self.assertEqual(decision.phase, "research")

    def test_chinese_keyword_coding(self) -> None:
        decision = self.router.route("编码")
        self.assertEqual(decision.phase, "coding")

    def test_chinese_keyword_testing(self) -> None:
        decision = self.router.route("测试")
        self.assertEqual(decision.phase, "testing")

    def test_chinese_keyword_idea(self) -> None:
        decision = self.router.route("创意")
        self.assertEqual(decision.phase, "idea")

    def test_chinese_keyword_doc(self) -> None:
        decision = self.router.route("文档")
        self.assertEqual(decision.phase, "doc")

    def test_multi_word_keyword_match(self) -> None:
        decision = self.router.route("run hackathon research")
        self.assertEqual(decision.phase, "research")

    def test_single_word_boundary_idea_not_in_selected_idea(self) -> None:
        """'idea' as single-word keyword should NOT match 'selected_idea' (word boundary)."""
        decision = self.router.route("selected_idea")
        self.assertNotEqual(decision.phase, "idea")

    def test_implement_routes_to_coding(self) -> None:
        decision = self.router.route("implement")
        self.assertEqual(decision.phase, "coding")

    def test_implementation_plan_routes_to_planning(self) -> None:
        """Multi-word 'implementation plan' should match planning, not coding."""
        decision = self.router.route("implementation plan")
        self.assertEqual(decision.phase, "planning")

    def test_case_insensitive(self) -> None:
        for text in ("RESEARCH", "Research", "rEsEaRcH"):
            decision = self.router.route(text)
            self.assertEqual(
                decision.phase, "research",
                f"'{text}' should be case-insensitive and route to research",
            )

    def test_phase_number_keywords(self) -> None:
        for i, phase in enumerate(PHASE_ORDER, 1):
            decision = self.router.route(f"phase {i}")
            self.assertEqual(
                decision.phase, phase,
                f"'phase {i}' should route to {phase}",
            )


class ConfidenceLevelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = SkillRouter()

    def test_single_match_confidence_095(self) -> None:
        decision = self.router.route("brainstorm")
        self.assertEqual(decision.confidence, 0.95)

    def test_ambiguous_resolved_by_specificity_confidence_09(self) -> None:
        """'select idea' (longer, more specific) should beat 'idea' alone."""
        decision = self.router.route("select idea")
        self.assertEqual(decision.confidence, 0.9)

    def test_empty_command_confidence_00(self) -> None:
        decision = self.router.route("")
        self.assertEqual(decision.confidence, 0.0)
        self.assertIsNone(decision.phase)

    def test_whitespace_only_confidence_00(self) -> None:
        decision = self.router.route("   ")
        self.assertEqual(decision.confidence, 0.0)
        self.assertIsNone(decision.phase)

    def test_no_match_confidence_01(self) -> None:
        decision = self.router.route("do something completely random and unrelated")
        self.assertEqual(decision.confidence, 0.1)
        self.assertIsNone(decision.phase)


class SourceFieldTests(unittest.TestCase):
    def test_rule_match_source_is_rule(self) -> None:
        router = SkillRouter()
        decision = router.route("research")
        self.assertEqual(decision.source, "rule")

    def test_no_match_source_is_none(self) -> None:
        router = SkillRouter()
        decision = router.route("xyzzy gibberish")
        self.assertEqual(decision.source, "none")

    def test_empty_command_source_is_none(self) -> None:
        router = SkillRouter()
        decision = router.route("")
        self.assertEqual(decision.source, "none")

    def test_fallback_classifier_source_is_llm(self) -> None:
        router = SkillRouter(fallback_classifier=lambda _: "coding")
        decision = router.route("build the thing now")
        self.assertEqual(decision.source, "llm")


class FallbackClassifierTests(unittest.TestCase):
    def test_fallback_invoked_when_no_keyword_match(self) -> None:
        router = SkillRouter(fallback_classifier=lambda _: "coding")
        decision = router.route("build the thing now")
        self.assertEqual(decision.phase, "coding")
        self.assertEqual(decision.confidence, 0.55)

    def test_fallback_returning_none_falls_through(self) -> None:
        router = SkillRouter(fallback_classifier=lambda _: None)
        decision = router.route("build the thing now")
        self.assertIsNone(decision.phase)
        self.assertEqual(decision.confidence, 0.1)

    def test_fallback_returning_invalid_phase_falls_through(self) -> None:
        router = SkillRouter(fallback_classifier=lambda _: "bogus")
        decision = router.route("build the thing now")
        self.assertIsNone(decision.phase)
        self.assertEqual(decision.confidence, 0.1)

    def test_no_fallback_configured(self) -> None:
        router = SkillRouter(fallback_classifier=None)
        decision = router.route("build the thing now")
        self.assertIsNone(decision.phase)
        self.assertEqual(decision.confidence, 0.1)

    def test_all_phases_are_routable(self) -> None:
        """Every phase in PHASE_ORDER should be reachable via at least one keyword."""
        router = SkillRouter()
        for phase in PHASE_ORDER:
            keywords = KEYWORD_MAP[phase]
            routed = False
            for kw in keywords:
                decision = router.route(kw)
                if decision.phase == phase:
                    routed = True
                    break
            self.assertTrue(routed, f"Phase '{phase}' has no working keyword route")


if __name__ == "__main__":
    unittest.main()
