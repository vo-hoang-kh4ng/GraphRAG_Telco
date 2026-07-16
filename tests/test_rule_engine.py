"""Unit tests for the rule engine. No Neo4j needed: facts are built directly
from the sample scenarios (src.kg.sample_data.SCENARIOS / DEVICES) the same
way fetch_facts() would assemble them from the graph.
"""

from src.kg.sample_data import DEVICES, SCENARIOS
from src.rules.rule_engine import evaluate_rules, merge_candidates


def facts_for_scenario(scenario):
    devices = {d["id"]: {"type": d["type"], "parent_id": d["depends_on"]} for d in DEVICES}
    children_of = {}
    for dev_id, info in devices.items():
        if info["parent_id"]:
            children_of.setdefault(info["parent_id"], []).append(dev_id)

    alarms_by_device = {}
    for a in scenario["alarms"]:
        alarms_by_device.setdefault(a["device"], []).append({"type": a["type"], "severity": a["severity"]})

    kpis_by_device = {}
    for k in scenario["kpi_anomalies"]:
        kpis_by_device.setdefault(k["device"], []).append({"name": k["kpi"], "value": k["value"], "status": k["status"]})

    return {
        "devices": devices,
        "children_of": children_of,
        "alarms_by_device": alarms_by_device,
        "kpis_by_device": kpis_by_device,
    }


def top_prediction(scenario):
    facts = facts_for_scenario(scenario)
    ranked = merge_candidates(evaluate_rules(facts))
    return ranked[0].device_id if ranked else None


def test_all_scenarios_top1_matches_ground_truth():
    for scenario in SCENARIOS:
        predicted = top_prediction(scenario)
        assert predicted == scenario["ground_truth_root_cause"], (
            f"{scenario['id']}: expected {scenario['ground_truth_root_cause']}, got {predicted}"
        )


def test_cascading_rule_beats_isolated_rule_confidence():
    scenario = next(s for s in SCENARIOS if s["id"] == "SCN-01")
    facts = facts_for_scenario(scenario)
    ranked = merge_candidates(evaluate_rules(facts))
    assert ranked[0].device_id == "TRANS-CORE-1"
    assert ranked[0].confidence >= 0.9


def test_no_facts_yields_no_candidates():
    facts = {"devices": {}, "children_of": {}, "alarms_by_device": {}, "kpis_by_device": {}}
    assert merge_candidates(evaluate_rules(facts)) == []
