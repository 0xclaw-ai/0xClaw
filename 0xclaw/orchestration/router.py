"""Phase router with rule-first and LLM fallback behavior."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

PHASE_ORDER = ("research", "idea", "selection", "planning", "coding", "testing", "doc")

KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "research": (
        "research",
        "run hackathon research",
        "run research",
        "phase 1",
        "调研",
        "研究",
    ),
    "idea": (
        "generate ideas",
        "brainstorm",
        "phase 2",
        "idea",
        "创意",
        "想法",
    ),
    "selection": (
        "select idea",
        "pick idea",
        "choose idea",
        "phase 3",
        "选题",
        "选择",
    ),
    "planning": (
        "plan",
        "plan architecture",
        "implementation plan",
        "phase 4",
        "planner",
        "规划",
        "计划",
    ),
    "coding": (
        "start coding",
        "implement",
        "phase 5",
        "coder",
        "开发",
        "编码",
        "实现",
    ),
    "testing": (
        "run tests",
        "validate",
        "phase 6",
        "tester",
        "测试",
        "验收",
    ),
    "doc": (
        "prepare docs",
        "submission",
        "phase 7",
        "documentation",
        "文档",
        "提交材料",
    ),
}


@dataclass(slots=True)
class RouteDecision:
    phase: str | None
    confidence: float
    reason: str
    source: str


def _keyword_matches(keyword: str, text: str) -> bool:
    """Match keyword against text.

    Multi-word keywords use simple substring matching.
    Single-word ASCII keywords use word-boundary matching to avoid false positives
    (e.g. 'idea' must not match 'selected_idea', 'implement' must not match
    'implementation').
    Non-ASCII keywords (e.g. Chinese) use substring matching because Python's
    word boundary only fires between word chars and non-word chars, and CJK
    characters are all word chars — so boundaries never match inside CJK text.
    """
    if " " in keyword or not keyword.isascii():
        return keyword in text
    return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))


class SkillRouter:
    """Route free-form input to pipeline phase."""

    def __init__(self, fallback_classifier: Callable[[str], str | None] | None = None):
        self._fallback_classifier = fallback_classifier

    def route(self, command: str) -> RouteDecision:
        text = (command or "").strip().lower()
        if not text:
            return RouteDecision(None, 0.0, "Empty command", "none")

        phase_scores: dict[str, int] = {}
        matched_keywords: dict[str, str] = {}
        for phase, keys in KEYWORD_MAP.items():
            matched = [k for k in keys if _keyword_matches(k, text)]
            if not matched:
                continue
            # Prefer more specific matches, e.g. "select idea" over the generic "idea".
            best = max(matched, key=len)
            phase_scores[phase] = len(best)
            matched_keywords[phase] = best

        matches = list(phase_scores)

        if len(matches) == 1:
            phase = matches[0]
            return RouteDecision(phase, 0.95, f"Matched keyword '{matched_keywords[phase]}' for {phase}", "rule")

        if len(matches) > 1:
            best_score = max(phase_scores.values())
            strongest = [phase for phase, score in phase_scores.items() if score == best_score]
            if len(strongest) == 1:
                phase = strongest[0]
                return RouteDecision(
                    phase,
                    0.9,
                    f"Preferred more specific keyword '{matched_keywords[phase]}' for {phase}",
                    "rule",
                )
            if self._fallback_classifier:
                pick = self._fallback_classifier(text)
                if pick in PHASE_ORDER:
                    return RouteDecision(pick, 0.65, f"Disambiguated by fallback from {matches}", "llm")
            return RouteDecision(None, 0.2, f"Conflicting phase keywords: {matches}", "rule")

        if self._fallback_classifier:
            pick = self._fallback_classifier(text)
            if pick in PHASE_ORDER:
                return RouteDecision(pick, 0.55, "Classified by fallback", "llm")

        return RouteDecision(None, 0.1, "No matching phase keyword", "none")
