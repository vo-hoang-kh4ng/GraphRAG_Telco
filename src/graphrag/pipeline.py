"""End-to-end GraphRAG pipeline (section 5.2 / 6, GraphRAG module).

retrieve subgraph -> build text context -> ask the LLM to explain / propose
a root cause. Returns a `GraphRAGResult` carrying both the raw subgraph
(for the demo UI) and the final diagnosis.
"""

from dataclasses import dataclass

from src.graphrag.context_builder import build_context_text
from src.graphrag.llm_client import get_llm_client
from src.graphrag.retriever import retrieve_subgraph


@dataclass
class GraphRAGResult:
    incident_id: str
    subgraph: dict
    context_text: str
    root_cause_device: str
    confidence: float
    explanation: str
    citations: list


def run_graphrag(conn, incident_id, llm_client=None):
    llm_client = llm_client or get_llm_client()

    subgraph = retrieve_subgraph(conn, incident_id)
    context_text = build_context_text(subgraph)
    diagnosis = llm_client.diagnose(context_text, subgraph)

    return GraphRAGResult(
        incident_id=incident_id,
        subgraph=subgraph,
        context_text=context_text,
        root_cause_device=diagnosis.root_cause_device,
        confidence=diagnosis.confidence,
        explanation=diagnosis.explanation,
        citations=diagnosis.citations,
    )
