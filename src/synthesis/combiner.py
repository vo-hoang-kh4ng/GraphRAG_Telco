"""Synthesis module (section 6): merges Rule Engine + GraphRAG output into a
single ranked recommendation for the NOC engineer, with a suggested action.

When both sources point at the same device the confidences are combined via
the same MYCIN-style certainty-factor formula used inside the rule engine,
plus a small cross-validation boost -- this is the "kiem chung cheo"
(cross-validation) behaviour called out in section 5.3 of the đề cương.
"""

from dataclasses import dataclass, field

CROSS_VALIDATION_BOOST = 0.1
MAX_CONFIDENCE = 0.99

# A GraphRAG/LLM candidate that no rule corroborates is discounted before
# ranking: rules are verified, deterministic domain logic, while a lone LLM
# opinion -- even a confident-sounding one -- is a single unverified guess.
# Without this, a real (non-mock) LLM's mis-calibrated self-reported
# confidence can outrank a correct, uncorroborated rule-engine candidate
# (observed in practice: Groq/Llama on SCN-05, see README). Rule-only
# candidates are NOT discounted the same way -- hand-authored production
# rules don't need a second opinion to be trusted.
UNCORROBORATED_GRAPHRAG_DISCOUNT = 0.7

ACTION_TEMPLATES = {
    "transmission": (
        "Kiem tra tuyen truyen dan / cap quang vat ly tai {device}; dieu phoi doi ky thuat hien "
        "truong kiem tra suy hao / dut soi quang neu can."
    ),
    "router": (
        "Kiem tra trang thai phan cung va module uplink cua router {device}; xem xet khoi dong lai "
        "hoac thay module neu loi lap lai."
    ),
    "olt": (
        "Kiem tra cong suat quang (optical power) tai OLT {device} va cac soi quang PON lien quan."
    ),
    "gnodeb": (
        "Kiem tra trang thai phan cung module vo tuyen tai gNodeB/BTS {device}; doi chieu lich su "
        "bao tri gan nhat."
    ),
    # DejaVu real-data device types (src/kg/dejavu_data.py) -- IT-ops/microservice, not telecom.
    "docker": (
        "Kiem tra tai nguyen CPU/memory va log cua container {device}; xem xet restart container "
        "hoac dieu chinh gioi han tai nguyen neu loi CPU/network lap lai."
    ),
    "db": (
        "Kiem tra connection pool, so session dang mo va trang thai ket noi cua database {device}; "
        "xem xet tang gioi han connection hoac kiem tra duong truyen mang toi DB neu gap loi "
        "'connection limit' / 'db close'."
    ),
    "os": (
        "Kiem tra tai nguyen he thong (CPU, network interface, hang doi goi tin) cua host {device}; "
        "xac dinh co phai do nghen bang thong hoac loi phan cung mang khong."
    ),
    "osb": (
        "Kiem tra Online Service Bus {device}: hang doi xu ly, ty le xu ly thanh cong (succ_rate); "
        "xac dinh co nghen tai tang gateway/entry-point khong."
    ),
}


@dataclass
class RankedCause:
    device_id: str
    combined_confidence: float
    sources: list = field(default_factory=list)
    rule_confidence: float = None
    rule_explanation: str = None
    graphrag_confidence: float = None
    graphrag_explanation: str = None
    agreement: bool = False


def _combine_certainty_factors(confidences):
    combined = 0.0
    for c in confidences:
        combined = combined + c * (1 - combined)
    return combined


def combine(rule_candidates, graphrag_result):
    """rule_candidates: list[RuleCandidate] (src.rules.rule_engine).
    graphrag_result: GraphRAGResult (src.graphrag.pipeline), possibly with
    root_cause_device=None if GraphRAG could not diagnose anything.
    """
    merged = {}

    for rc in rule_candidates:
        merged[rc.device_id] = {
            "rule_confidence": rc.confidence,
            "rule_explanation": rc.explanation,
            "graphrag_confidence": None,
            "graphrag_explanation": None,
        }

    if graphrag_result and graphrag_result.root_cause_device:
        entry = merged.setdefault(
            graphrag_result.root_cause_device,
            {"rule_confidence": None, "rule_explanation": None, "graphrag_confidence": None, "graphrag_explanation": None},
        )
        entry["graphrag_confidence"] = graphrag_result.confidence
        entry["graphrag_explanation"] = graphrag_result.explanation

    ranked = []
    for device_id, e in merged.items():
        rule_conf = e["rule_confidence"]
        graphrag_conf = e["graphrag_confidence"]
        agreement = rule_conf is not None and graphrag_conf is not None

        effective_graphrag_conf = graphrag_conf
        if graphrag_conf is not None and rule_conf is None:
            effective_graphrag_conf = graphrag_conf * UNCORROBORATED_GRAPHRAG_DISCOUNT

        confs = [c for c in (rule_conf, effective_graphrag_conf) if c is not None]
        combined_conf = _combine_certainty_factors(confs)
        if agreement:
            combined_conf = min(MAX_CONFIDENCE, combined_conf + CROSS_VALIDATION_BOOST)
        sources = []
        if e["rule_confidence"] is not None:
            sources.append("rule_engine")
        if e["graphrag_confidence"] is not None:
            sources.append("graphrag")

        ranked.append(
            RankedCause(
                device_id=device_id,
                combined_confidence=round(combined_conf, 4),
                sources=sources,
                rule_confidence=e["rule_confidence"],
                rule_explanation=e["rule_explanation"],
                graphrag_confidence=e["graphrag_confidence"],
                graphrag_explanation=e["graphrag_explanation"],
                agreement=agreement,
            )
        )

    ranked.sort(key=lambda r: r.combined_confidence, reverse=True)
    return ranked


def suggest_action(device_id, subgraph):
    device = next((d for d in subgraph["devices"] if d["id"] == device_id), None)
    device_type = device["type"] if device else None
    template = ACTION_TEMPLATES.get(device_type, "Kiem tra thu cong thiet bi {device} de xac dinh nguyen nhan cu the.")
    return template.format(device=device_id)
