"""CLI demo: runs the full diagnosis flow (Rule Engine + GraphRAG + synthesis)
on one incident scenario and prints every stage (section 6 / 7: "demo/prototype
minh hoa toan bo luong xu ly tren mot tap kich ban su co mau").

Usage:
    python -m src.demo                 # list scenarios and run the first one
    python -m src.demo --scenario SCN-03
    python -m src.demo --list
"""

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.graphrag.pipeline import run_graphrag
from src.kg import graph_builder
from src.kg.connection import Neo4jConnection
from src.kg.sample_data import SCENARIOS
from src.rules.rule_engine import run_rule_engine
from src.synthesis.combiner import combine, suggest_action

console = Console()


def print_scenario_list():
    table = Table(title="Cac kich ban su co mau")
    table.add_column("ID")
    table.add_column("Ten")
    table.add_column("Root cause thuc te")
    for s in SCENARIOS:
        table.add_row(s["id"], s["name"], s["ground_truth_root_cause"])
    console.print(table)


def print_rule_candidates(rule_candidates):
    table = Table(title="Ket qua Rule Engine (IF-THEN reasoning)")
    table.add_column("Thiet bi")
    table.add_column("Do tin cay (CF)")
    table.add_column("Luat kich hoat")
    for c in rule_candidates:
        table.add_row(c.device_id, f"{c.confidence:.2f}", c.rule_id)
    console.print(table)
    if rule_candidates:
        console.print(Panel(rule_candidates[0].explanation, title=f"Giai thich chi tiet: {rule_candidates[0].device_id}"))


def print_graphrag_result(result):
    console.print(Panel(result.context_text, title="Ngu canh truy xuat tu Knowledge Graph (GraphRAG context)"))
    console.print(
        Panel(
            f"Nguyen nhan de xuat: [bold]{result.root_cause_device}[/bold] "
            f"(confidence={result.confidence:.2f})\n\n{result.explanation}"
            + (f"\n\nTrich dan: {', '.join(result.citations)}" if result.citations else ""),
            title="Ket qua GraphRAG (LLM diagnosis)",
        )
    )


def print_final_recommendation(ranked, subgraph):
    table = Table(title="Khuyen nghi tong hop (Rule Engine + GraphRAG)")
    table.add_column("Hang")
    table.add_column("Thiet bi")
    table.add_column("Do tin cay tong hop")
    table.add_column("Nguon")
    table.add_column("Dong thuan?")
    for i, r in enumerate(ranked, start=1):
        table.add_row(
            str(i),
            r.device_id,
            f"{r.combined_confidence:.2f}",
            "+".join(r.sources),
            "CO" if r.agreement else "khong",
        )
    console.print(table)

    if ranked:
        top = ranked[0]
        action = suggest_action(top.device_id, subgraph)
        console.print(
            Panel(
                f"Nguyen nhan goc re duoc de xuat: [bold]{top.device_id}[/bold] "
                f"(do tin cay {top.combined_confidence:.2f}, nguon: {'+'.join(top.sources)})\n\n"
                f"Huong xu ly de xuat: {action}",
                title="Khuyen nghi cuoi cung cho ky su van hanh",
                style="green",
            )
        )


def run_demo(conn, scenario):
    console.rule(f"[bold]{scenario['id']} - {scenario['name']}[/bold]")
    console.print(scenario["description"])

    graph_builder.load_scenario(conn, scenario)

    rule_candidates = run_rule_engine(conn)
    print_rule_candidates(rule_candidates)

    graphrag_result = run_graphrag(conn, scenario["id"])
    print_graphrag_result(graphrag_result)

    ranked = combine(rule_candidates, graphrag_result)
    print_final_recommendation(ranked, graphrag_result.subgraph)

    console.print(f"\n[dim]Ground truth (danh cho danh gia): {scenario['ground_truth_root_cause']}[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Demo he thong chan doan su co mang vien thong")
    parser.add_argument("--scenario", help="Scenario id, vi du SCN-01")
    parser.add_argument("--list", action="store_true", help="Chi liet ke cac scenario roi thoat")
    args = parser.parse_args()

    if args.list:
        print_scenario_list()
        return

    scenario = SCENARIOS[0]
    if args.scenario:
        matches = [s for s in SCENARIOS if s["id"] == args.scenario]
        if not matches:
            console.print(f"[red]Khong tim thay scenario {args.scenario}[/red]")
            print_scenario_list()
            return
        scenario = matches[0]

    with Neo4jConnection() as conn:
        graph_builder.bootstrap(conn)
        run_demo(conn, scenario)


if __name__ == "__main__":
    main()
