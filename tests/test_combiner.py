"""Tests for the synthesis/combiner module. Uses lightweight fakes for the
rule-engine and GraphRAG outputs -- no Neo4j needed.
"""

from dataclasses import dataclass, field

from src.synthesis.combiner import combine


@dataclass
class FakeRuleCandidate:
    device_id: str
    confidence: float
    rule_id: str = "R1"
    rule_name: str = "fake"
    explanation: str = "fake rule explanation"


@dataclass
class FakeGraphRAGResult:
    root_cause_device: str
    confidence: float
    explanation: str = "fake graphrag explanation"
    citations: list = field(default_factory=list)


def test_agreement_boosts_confidence_above_either_alone():
    rule_candidates = [FakeRuleCandidate(device_id="TRANS-CORE-1", confidence=0.8)]
    graphrag_result = FakeGraphRAGResult(root_cause_device="TRANS-CORE-1", confidence=0.7)

    ranked = combine(rule_candidates, graphrag_result)

    assert ranked[0].device_id == "TRANS-CORE-1"
    assert ranked[0].agreement is True
    assert ranked[0].combined_confidence > 0.8
    assert set(ranked[0].sources) == {"rule_engine", "graphrag"}


def test_disagreement_keeps_both_candidates_separate():
    rule_candidates = [FakeRuleCandidate(device_id="RTR-EDGE-1", confidence=0.75)]
    graphrag_result = FakeGraphRAGResult(root_cause_device="GNB-A2", confidence=0.6)

    ranked = combine(rule_candidates, graphrag_result)
    device_ids = {r.device_id for r in ranked}

    assert device_ids == {"RTR-EDGE-1", "GNB-A2"}
    assert all(not r.agreement for r in ranked)
    # Rule engine's higher-confidence candidate should rank first.
    assert ranked[0].device_id == "RTR-EDGE-1"


def test_graphrag_none_root_cause_is_ignored():
    rule_candidates = [FakeRuleCandidate(device_id="OLT-B1", confidence=0.55)]
    graphrag_result = FakeGraphRAGResult(root_cause_device=None, confidence=0.0)

    ranked = combine(rule_candidates, graphrag_result)

    assert len(ranked) == 1
    assert ranked[0].device_id == "OLT-B1"
    assert ranked[0].sources == ["rule_engine"]


def test_uncorroborated_graphrag_does_not_outrank_correct_rule_only_candidate():
    """Regression test: a real (non-mock) LLM can be confidently wrong (observed
    with Groq/Llama on SCN-05 -- see README). An uncorroborated GraphRAG
    candidate must not outrank a correct, uncorroborated rule-engine candidate
    just because the LLM reported a higher raw confidence.
    """
    rule_candidates = [FakeRuleCandidate(device_id="OLT-B1", confidence=0.65)]
    graphrag_result = FakeGraphRAGResult(root_cause_device="RTR-EDGE-2", confidence=0.8)

    ranked = combine(rule_candidates, graphrag_result)

    assert ranked[0].device_id == "OLT-B1"
    # Raw (undiscounted) confidences are still reported for transparency.
    wrong = next(r for r in ranked if r.device_id == "RTR-EDGE-2")
    assert wrong.graphrag_confidence == 0.8
