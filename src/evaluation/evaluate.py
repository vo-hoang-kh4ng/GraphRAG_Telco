"""Evaluation (section 7 / 9): compares diagnostic accuracy of rule-only,
GraphRAG-only and combined (rule + GraphRAG) approaches on the sample
incident scenarios, against their known ground-truth root cause.
"""

from rich.console import Console
from rich.table import Table

from src.graphrag.llm_client import MockLLM
from src.graphrag.pipeline import run_graphrag
from src.kg import graph_builder
from src.kg.connection import Neo4jConnection
from src.kg.sample_data import SCENARIOS
from src.rules.rule_engine import run_rule_engine
from src.synthesis.combiner import combine

console = Console()


def _top_device(candidates):
    return candidates[0].device_id if candidates else None


def evaluate(conn, llm_client=None):
    rows = []
    llm_client = llm_client or MockLLM()

    for scenario in SCENARIOS:
        graph_builder.load_scenario(conn, scenario)

        rule_candidates = run_rule_engine(conn)
        rule_pred = _top_device(rule_candidates)

        graphrag_result = run_graphrag(conn, scenario["id"], llm_client=llm_client)
        graphrag_pred = graphrag_result.root_cause_device

        combined_ranked = combine(rule_candidates, graphrag_result)
        combined_pred = _top_device(combined_ranked)

        truth = scenario["ground_truth_root_cause"]
        rows.append(
            {
                "scenario": scenario["id"],
                "name": scenario["name"],
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
    table = Table(title="Danh gia do chinh xac chan doan (rule-only vs GraphRAG-only vs combined)")
    table.add_column("Scenario")
    table.add_column("Ground truth")
    table.add_column("Rule-only")
    table.add_column("GraphRAG-only")
    table.add_column("Combined")

    def fmt(pred, correct):
        mark = "[green]OK[/green]" if correct else "[red]SAI[/red]"
        return f"{pred} {mark}"

    for r in rows:
        table.add_row(
            r["scenario"],
            r["truth"],
            fmt(r["rule_pred"], r["rule_correct"]),
            fmt(r["graphrag_pred"], r["graphrag_correct"]),
            fmt(r["combined_pred"], r["combined_correct"]),
        )
    console.print(table)

    n = len(rows)
    for key, label in [("rule_correct", "Rule-only"), ("graphrag_correct", "GraphRAG-only"), ("combined_correct", "Combined")]:
        acc = sum(1 for r in rows if r[key]) / n
        console.print(f"{label} accuracy: {acc:.0%} ({sum(1 for r in rows if r[key])}/{n})")


def main():
    with Neo4jConnection() as conn:
        graph_builder.bootstrap(conn)
        rows = evaluate(conn)
        print_report(rows)


if __name__ == "__main__":
    main()
