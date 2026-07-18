"""Error-analysis evaluation: runs a fixed, curated sample through BOTH
MockLLM and a real LLM (LLM_PROVIDER, e.g. Groq), to get (a) a real number
showing how GraphRAG-only accuracy actually holds up with a real LLM versus
the deterministic MockLLM, and (b) full detail of every wrong prediction for
a qualitative "Error Analysis" section in the report.

Deliberately does NOT run the full 78-incident DejaVu set through a real
LLM (slow, burns API quota, and Top-1 accuracy is already saturated at 100%
with MockLLM there -- see the brainstorm decision this script implements).
Instead: all 5 telecom scenarios (small, already central to the report) +
a curated 15-incident DejaVu sample selected for STRUCTURAL DIFFICULTY, not
randomly:
  - 12 cases on the 4 "hardest" devices (docker_001..004), each of which has
    5 DEPENDS_ON parents -- the most plausible-looking wrong answers for an
    LLM to pick (this is exactly the shape of the real DEJAVU-002 mistake
    observed live: LLM picked db_007, a parent, instead of the device
    itself). One case per unique (device, fault_type) combination, so all
    3 fault types that occur on these devices are covered for each device.
  - 3 cases on 2-parent devices (docker_005..008), for a difficulty-spectrum
    comparison point.

Usage:
    python -m src.evaluation.evaluate_real_llm_sample
"""

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

RESULTS_FILE = Path(__file__).parent.parent.parent / "report" / "real_llm_sample_results.json"

from src.graphrag.llm_client import MockLLM, get_llm_client
from src.graphrag.pipeline import run_graphrag
from src.kg import graph_builder
from src.kg.connection import Neo4jConnection
from src.kg.dejavu_data import DEVICES as DEJAVU_DEVICES
from src.kg.dejavu_data import INCIDENTS as DEJAVU_INCIDENTS
from src.kg.sample_data import SCENARIOS
from src.rules.rule_engine import run_rule_engine
from src.synthesis.combiner import combine

console = Console(legacy_windows=False)

SELECTED_DEJAVU_IDS = [
    # 12 hard cases: docker_001..004 (5 parents each), one per (device, fault_type)
    "DEJAVU-001", "DEJAVU-002", "DEJAVU-003", "DEJAVU-004",
    "DEJAVU-006", "DEJAVU-007", "DEJAVU-008", "DEJAVU-013",
    "DEJAVU-027", "DEJAVU-029", "DEJAVU-032", "DEJAVU-064",
    # 3 medium cases: docker_005..008 (2 parents each)
    "DEJAVU-009", "DEJAVU-010", "DEJAVU-014",
]


def _top_device(candidates):
    return candidates[0].device_id if candidates else None


def _run_one(conn, incident, llm_client):
    graph_builder.load_scenario(conn, incident)
    rule_candidates = run_rule_engine(conn)
    rule_pred = _top_device(rule_candidates)

    graphrag_result = run_graphrag(conn, incident["id"], llm_client=llm_client)
    graphrag_pred = graphrag_result.root_cause_device

    combined_ranked = combine(rule_candidates, graphrag_result)
    combined_pred = _top_device(combined_ranked)

    truth = incident["ground_truth_root_cause"]
    return {
        "id": incident["id"],
        "name": incident["name"],
        "truth": truth,
        "rule_pred": rule_pred,
        "rule_correct": rule_pred == truth,
        "graphrag_pred": graphrag_pred,
        "graphrag_correct": graphrag_pred == truth,
        "graphrag_explanation": graphrag_result.explanation,
        "combined_pred": combined_pred,
        "combined_correct": combined_pred == truth,
        "combined_sources": None,
        "agreement": combined_ranked[0].agreement if combined_ranked else False,
    }


def run_sample(conn, llm_client):
    rows = []

    graph_builder.bootstrap(conn)
    for scenario in SCENARIOS:
        rows.append(_run_one(conn, scenario, llm_client))

    dejavu_by_id = {i["id"]: i for i in DEJAVU_INCIDENTS}
    graph_builder.bootstrap_devices_only(conn, DEJAVU_DEVICES)
    for inc_id in SELECTED_DEJAVU_IDS:
        rows.append(_run_one(conn, dejavu_by_id[inc_id], llm_client))

    return rows


def _accuracy(rows, key):
    n = len(rows)
    correct = sum(1 for r in rows if r[key])
    return correct, n, correct / n


def print_comparison(mock_rows, real_rows, provider_name):
    table = Table(title=f"So sanh MockLLM vs {provider_name} tren mau 20 case (5 vien thong + 15 DejaVu kho)")
    table.add_column("Phuong phap")
    table.add_column("MockLLM")
    table.add_column(provider_name)

    for key, label in [("rule_correct", "Rule-only"), ("graphrag_correct", "GraphRAG-only"), ("combined_correct", "Combined")]:
        mc, mn, macc = _accuracy(mock_rows, key)
        rc, rn, racc = _accuracy(real_rows, key)
        table.add_row(label, f"{macc:.0%} ({mc}/{mn})", f"{racc:.0%} ({rc}/{rn})")
    console.print(table)

    console.print("\n[bold]Cac truong hop GraphRAG (LLM that) tra loi SAI (nguyen lieu cho Error Analysis):[/bold]")
    wrong_table = Table()
    wrong_table.add_column("ID")
    wrong_table.add_column("Ground truth")
    wrong_table.add_column("GraphRAG doan")
    wrong_table.add_column("Combined")
    wrong_table.add_column("Giai thich cua LLM")
    any_wrong = False
    for r in real_rows:
        if not r["graphrag_correct"]:
            any_wrong = True
            combined_mark = "[green]OK[/green]" if r["combined_correct"] else "[red]SAI[/red]"
            wrong_table.add_row(
                r["id"], r["truth"], r["graphrag_pred"] or "None",
                f"{r['combined_pred']} {combined_mark}",
                (r["graphrag_explanation"] or "")[:120],
            )
    if any_wrong:
        try:
            console.print(wrong_table)
        except UnicodeEncodeError:
            console.print(
                "[yellow](Bang chi tiet chua encode duoc tren console nay -- xem file JSON day du thay the.)[/yellow]"
            )
    else:
        console.print("[green]Khong co truong hop nao GraphRAG sai trong mau nay.[/green]")


def _save_results_json(mock_rows, real_rows, provider_name):
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider_name": provider_name,
        "mock_rows": mock_rows,
        "real_rows": real_rows,
    }
    RESULTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"\n[dim]Da luu toan bo ket qua (kem giai thich LLM day du) vao {RESULTS_FILE}[/dim]")


def main():
    with Neo4jConnection() as conn:
        console.print("[bold]Dang chay voi MockLLM...[/bold]")
        mock_rows = run_sample(conn, MockLLM())

        real_client = get_llm_client()
        provider_name = type(real_client).__name__
        if provider_name == "MockLLM":
            console.print(
                "[yellow]LLM_PROVIDER dang la 'mock' -- dat LLM_PROVIDER=groq (hoac anthropic/openai) "
                "trong .env de chay so sanh voi LLM that.[/yellow]"
            )
            return
        console.print(f"[bold]Dang chay voi {provider_name} (LLM that)...[/bold]")
        real_rows = run_sample(conn, real_client)

        _save_results_json(mock_rows, real_rows, provider_name)
        print_comparison(mock_rows, real_rows, provider_name)


if __name__ == "__main__":
    main()
