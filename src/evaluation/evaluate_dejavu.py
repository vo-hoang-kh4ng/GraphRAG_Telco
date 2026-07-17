"""Evaluation on REAL fault data (NetManAIOps/DejaVu, see src/kg/dejavu_data.py)
-- a separate report from src/evaluation/evaluate.py's synthetic telecom
scenarios, deliberately not merged into the same table/accuracy number since
the two datasets test different things (see dejavu_data.py's module
docstring for the full caveat: real but non-telecom, all single-device
isolated faults, no cascading ground truth here).
"""

from rich.console import Console
from rich.table import Table

from src.graphrag.llm_client import MockLLM
from src.graphrag.pipeline import run_graphrag
from src.kg import graph_builder
from src.kg.connection import Neo4jConnection
from src.kg.dejavu_data import DEVICES as DEJAVU_DEVICES
from src.kg.dejavu_data import INCIDENTS as DEJAVU_INCIDENTS
from src.rules.rule_engine import run_rule_engine
from src.synthesis.combiner import combine

console = Console()


def _top_device(candidates):
    return candidates[0].device_id if candidates else None


def evaluate(conn, incidents=None):
    incidents = incidents if incidents is not None else DEJAVU_INCIDENTS
    llm_client = MockLLM()
    rows = []

    for incident in incidents:
        graph_builder.load_scenario(conn, incident)

        rule_candidates = run_rule_engine(conn)
        rule_pred = _top_device(rule_candidates)

        graphrag_result = run_graphrag(conn, incident["id"], llm_client=llm_client)
        graphrag_pred = graphrag_result.root_cause_device

        combined_ranked = combine(rule_candidates, graphrag_result)
        combined_pred = _top_device(combined_ranked)

        truth = incident["ground_truth_root_cause"]
        rows.append(
            {
                "id": incident["id"],
                "name": incident["name"],
                "truth": truth,
                "rule_pred": rule_pred,
                "rule_correct": rule_pred == truth,
                "graphrag_pred": graphrag_pred,
                "graphrag_correct": graphrag_pred == truth,
                "combined_pred": combined_pred,
                "combined_correct": combined_pred == truth,
            }
        )

    return rows


def print_report(rows):
    n = len(rows)
    console.print(
        f"\n[bold]Danh gia tren du lieu THAT (NetManAIOps/DejaVu, CC-BY 4.0, khong phai vien "
        f"thong -- xem caveat trong src/kg/dejavu_data.py)[/bold]"
    )
    console.print(f"Tong so su co that: {n} (deu la loi don-thiet-bi, khong co case cascade)\n")

    for key, label in [("rule_correct", "Rule-only"), ("graphrag_correct", "GraphRAG-only"), ("combined_correct", "Combined")]:
        correct = sum(1 for r in rows if r[key])
        console.print(f"{label} accuracy: {correct / n:.1%} ({correct}/{n})")

    mismatches = [r for r in rows if not r["combined_correct"]]
    if mismatches:
        table = Table(title=f"Cac truong hop combined du doan SAI ({len(mismatches)}/{n})")
        table.add_column("Incident")
        table.add_column("Ground truth")
        table.add_column("Rule-only")
        table.add_column("GraphRAG-only")
        table.add_column("Combined")
        for r in mismatches:
            table.add_row(r["id"], r["truth"], str(r["rule_pred"]), str(r["graphrag_pred"]), str(r["combined_pred"]))
        console.print(table)
    else:
        console.print("\n[green]Combined dung tren toan bo su co that.[/green]")


def main():
    with Neo4jConnection() as conn:
        graph_builder.bootstrap_devices_only(conn, DEJAVU_DEVICES)
        rows = evaluate(conn)
        print_report(rows)


if __name__ == "__main__":
    main()
