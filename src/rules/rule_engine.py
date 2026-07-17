"""IF-THEN production rule engine for root-cause narrowing (section 5.3 / 6).

Facts (alarms, KPI anomalies, topology) are pulled from the Neo4j KG once per
run, then a small set of hand-authored rules -- encoding NOC diagnostic
experience -- are evaluated in plain Python. Rules produce (device, rule
confidence) pairs; when several rules point at the same device their
confidences are combined with the classic MYCIN-style certainty-factor
formula CF12 = CF1 + CF2 * (1 - CF1), a natural fit for a rule-based
expert-system component in a knowledge-representation course.
"""

from dataclasses import dataclass

from src.kg import schema

SIGNAL_LOSS_ALARM_TYPES = {"LOSS_OF_SIGNAL", "CELL_DOWN", "LOW_THROUGHPUT"}
LINK_FAILURE_ALARM_TYPES = {"LINK_DOWN"}


@dataclass
class RuleCandidate:
    device_id: str
    confidence: float
    rule_id: str
    rule_name: str
    explanation: str


def fetch_facts(conn):
    """Pull the current KG state needed by the rules into plain Python structures.

    A device may DEPENDS_ON more than one parent (e.g. a service that calls
    several backends, or runs on a host it also depends on) -- topology is a
    DAG, not necessarily a tree, so `parents_of[device]` is always a list.
    """

    device_rows = conn.run(
        f"""
        MATCH (d:{schema.LABEL_DEVICE})
        OPTIONAL MATCH (d)-[:{schema.REL_DEPENDS_ON}]->(parent:{schema.LABEL_DEVICE})
        RETURN d.id AS id, d.type AS type, parent.id AS parent_id
        """
    )
    devices = {}
    parents_of = {}
    for r in device_rows:
        devices.setdefault(r["id"], {"type": r["type"]})
        parents_of.setdefault(r["id"], [])
        if r["parent_id"]:
            parents_of[r["id"]].append(r["parent_id"])

    children_of = {}
    for dev_id, parents in parents_of.items():
        for parent_id in parents:
            children_of.setdefault(parent_id, []).append(dev_id)

    alarm_rows = conn.run(
        f"""
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_RAISED_ALARM}]->(a:{schema.LABEL_ALARM})
        RETURN d.id AS device_id, a.type AS type, a.severity AS severity
        """
    )
    alarms_by_device = {}
    for r in alarm_rows:
        alarms_by_device.setdefault(r["device_id"], []).append({"type": r["type"], "severity": r["severity"]})

    kpi_rows = conn.run(
        f"""
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_HAS_KPI}]->(k:{schema.LABEL_KPI})
        RETURN d.id AS device_id, k.name AS name, k.value AS value, k.status AS status
        """
    )
    kpis_by_device = {}
    for r in kpi_rows:
        kpis_by_device.setdefault(r["device_id"], []).append(
            {"name": r["name"], "value": r["value"], "status": r["status"]}
        )

    return {
        "devices": devices,
        "parents_of": parents_of,
        "children_of": children_of,
        "alarms_by_device": alarms_by_device,
        "kpis_by_device": kpis_by_device,
    }


def _has_alarm_of_type(alarms_by_device, device_id, alarm_types):
    return any(a["type"] in alarm_types for a in alarms_by_device.get(device_id, []))


def _has_any_alarm(alarms_by_device, device_id):
    return bool(alarms_by_device.get(device_id))


# --- Rule A: cascading parent failure ---------------------------------------
def rule_cascading_parent_failure(facts):
    """IF X raises a link-failure alarm AND every direct child of X raises a
    signal-loss-type alarm THEN root cause = X (matches the đề cương's example rule).
    """
    candidates = []
    devices, children_of = facts["devices"], facts["children_of"]
    alarms_by_device = facts["alarms_by_device"]

    for dev_id in devices:
        if not _has_alarm_of_type(alarms_by_device, dev_id, LINK_FAILURE_ALARM_TYPES):
            continue
        children = children_of.get(dev_id, [])
        if not children:
            continue
        if all(_has_alarm_of_type(alarms_by_device, c, SIGNAL_LOSS_ALARM_TYPES) for c in children):
            candidates.append(
                RuleCandidate(
                    device_id=dev_id,
                    confidence=0.95,
                    rule_id="R1_cascading_parent_failure",
                    rule_name="Cascading parent failure",
                    explanation=(
                        f"{dev_id} phat canh bao mat ket noi (Link_Down) va toan bo "
                        f"{len(children)} thiet bi con ({', '.join(children)}) deu phat canh bao "
                        f"mat tin hieu -> nguyen nhan goc re nhieu kha nang la {dev_id}, khong phai "
                        f"cac thiet bi con."
                    ),
                )
            )
    return candidates


# --- Rule B: isolated device fault ------------------------------------------
def rule_isolated_device_fault(facts):
    """IF X itself raises an alarm AND none of X's parents have an alarm AND
    X's children (if any) show no alarm (KPI degradation at most) THEN root
    cause = X.
    """
    candidates = []
    devices, children_of, parents_of = facts["devices"], facts["children_of"], facts["parents_of"]
    alarms_by_device = facts["alarms_by_device"]

    for dev_id in devices:
        if not _has_any_alarm(alarms_by_device, dev_id):
            continue
        parents = parents_of.get(dev_id, [])
        if any(_has_any_alarm(alarms_by_device, p) for p in parents):
            continue
        children = children_of.get(dev_id, [])
        if any(_has_any_alarm(alarms_by_device, c) for c in children):
            continue
        candidates.append(
            RuleCandidate(
                device_id=dev_id,
                confidence=0.85,
                rule_id="R2_isolated_device_fault",
                rule_name="Isolated device fault",
                explanation=(
                    f"{dev_id} phat canh bao trong khi (cac) thiet bi cha"
                    f"{(' (' + ', '.join(parents) + ')') if parents else ''} va cac thiet bi con "
                    f"khong phat canh bao nao -> su co khu tru tai {dev_id}, khong lan truyen."
                ),
            )
        )
    return candidates


# --- Rule C: shared-parent sibling pattern ----------------------------------
def rule_shared_parent_sibling_pattern(facts):
    """IF >=2 sibling devices under the same parent P raise alarms AND P itself
    has no explicit alarm THEN P is a likely shared point of failure.
    """
    candidates = []
    children_of = facts["children_of"]
    alarms_by_device = facts["alarms_by_device"]

    for parent_id, children in children_of.items():
        if _has_any_alarm(alarms_by_device, parent_id):
            continue
        alarmed_children = [c for c in children if _has_any_alarm(alarms_by_device, c)]
        if len(alarmed_children) >= 2:
            candidates.append(
                RuleCandidate(
                    device_id=parent_id,
                    confidence=0.75,
                    rule_id="R3_shared_parent_sibling_pattern",
                    rule_name="Shared-parent sibling pattern",
                    explanation=(
                        f"{len(alarmed_children)} thiet bi con cua {parent_id} "
                        f"({', '.join(alarmed_children)}) cung phat canh bao du {parent_id} chua co "
                        f"canh bao tuong minh -> nhieu kha nang {parent_id} la diem loi chung "
                        f"(single point of failure)."
                    ),
                )
            )
    return candidates


# --- Rule E: KPI-only early warning ------------------------------------------
def rule_kpi_only_early_warning(facts):
    """IF X has a KPI reading in warning/critical status AND no alarm exists yet
    for X THEN X is a lower-confidence early-warning candidate.
    """
    candidates = []
    alarms_by_device = facts["alarms_by_device"]
    kpis_by_device = facts["kpis_by_device"]

    for dev_id, kpis in kpis_by_device.items():
        if _has_any_alarm(alarms_by_device, dev_id):
            continue
        bad_kpis = [k for k in kpis if k["status"] in ("warning", "critical")]
        if not bad_kpis:
            continue
        confidence = 0.65 if any(k["status"] == "critical" for k in bad_kpis) else 0.5
        kpi_desc = ", ".join(f"{k['name']}={k['value']} ({k['status']})" for k in bad_kpis)
        candidates.append(
            RuleCandidate(
                device_id=dev_id,
                confidence=confidence,
                rule_id="R4_kpi_only_early_warning",
                rule_name="KPI-only early warning",
                explanation=(
                    f"{dev_id} co KPI vuot nguong ({kpi_desc}) dù chua sinh canh bao chinh thuc "
                    f"-> nghi ngo {dev_id} dang suy giam hieu nang (early warning)."
                ),
            )
        )
    return candidates


ALL_RULES = [
    rule_cascading_parent_failure,
    rule_isolated_device_fault,
    rule_shared_parent_sibling_pattern,
    rule_kpi_only_early_warning,
]


def _combine_certainty_factors(confidences):
    """MYCIN-style certainty-factor combination: CF12 = CF1 + CF2*(1-CF1)."""
    combined = 0.0
    for c in confidences:
        combined = combined + c * (1 - combined)
    return round(combined, 4)


def evaluate_rules(facts):
    """Run every rule against `facts` and return the raw (non-deduplicated) list of RuleCandidate."""
    raw_candidates = []
    for rule_fn in ALL_RULES:
        raw_candidates.extend(rule_fn(facts))
    return raw_candidates


def merge_candidates(raw_candidates):
    """De-duplicate candidates by device, combining confidences across every
    rule that fired for that device (certainty-factor combination), and
    return them ranked highest-confidence first.
    """
    by_device = {}
    for c in raw_candidates:
        by_device.setdefault(c.device_id, []).append(c)

    merged = []
    for device_id, cands in by_device.items():
        combined_conf = _combine_certainty_factors([c.confidence for c in cands])
        explanation = " | ".join(f"[{c.rule_id}] {c.explanation}" for c in cands)
        fired_rules = [c.rule_id for c in cands]
        merged.append(
            RuleCandidate(
                device_id=device_id,
                confidence=combined_conf,
                rule_id="+".join(fired_rules),
                rule_name="+".join(sorted({c.rule_name for c in cands})),
                explanation=explanation,
            )
        )

    merged.sort(key=lambda c: c.confidence, reverse=True)
    return merged


def run_rule_engine(conn):
    """Evaluate all rules against the current KG state and return a ranked,
    de-duplicated list of RuleCandidate (one per device, confidence combined
    across every rule that fired for that device).
    """
    facts = fetch_facts(conn)
    raw_candidates = evaluate_rules(facts)
    return merge_candidates(raw_candidates)
