from __future__ import annotations


def test_router_30_samples_accuracy(router_mod):
    router = router_mod.SkillRouter()

    samples = [
        ("run hackathon research", "research"),
        ("run research now", "research"),
        ("phase 1", "research"),
        ("先做调研", "research"),
        ("开始研究阶段", "research"),
        ("generate ideas", "idea"),
        ("brainstorm 3 ideas", "idea"),
        ("phase 2", "idea"),
        ("开始创意阶段", "idea"),
        ("给我一些想法", "idea"),
        ("select idea", "selection"),
        ("pick idea", "selection"),
        ("phase 3", "selection"),
        ("帮我选题", "selection"),
        ("选择方案", "selection"),
        ("plan architecture", "planning"),
        ("make implementation plan", "planning"),
        ("phase 4", "planning"),
        ("开始技术规划", "planning"),
        ("规划一下", "planning"),
        ("start coding", "coding"),
        ("implement tasks", "coding"),
        ("phase 5", "coding"),
        ("开始实现", "coding"),
        ("编码阶段", "coding"),
        ("run tests", "testing"),
        ("phase 6", "testing"),
        ("开始测试", "testing"),
        ("prepare docs", "doc"),
        ("phase 7", "doc"),
    ]

    hit = 0
    for text, expected in samples:
        decision = router.route(text)
        if decision.phase == expected:
            hit += 1

    assert hit / len(samples) >= 0.9


def test_router_conflict_uses_fallback(router_mod):
    router = router_mod.SkillRouter(fallback_classifier=lambda _t: "planning")
    decision = router.route("plan architecture then run tests")
    assert decision.phase == "planning"
    assert decision.source == "llm"


def test_router_empty(router_mod):
    router = router_mod.SkillRouter()
    decision = router.route("")
    assert decision.phase is None
    assert "Empty" in decision.reason
