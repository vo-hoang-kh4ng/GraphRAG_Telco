"""Visual (node/edge) rendering of a retrieved GraphRAG subgraph, for the
Streamlit demo (app.py) only -- not used by the core CLI/evaluation
pipeline, so `pyvis` stays an optional dependency of the web demo.
"""

from pyvis.network import Network

ALARM_COLOR = "#e74c3c"  # red -- device currently has an active alarm
KPI_ONLY_COLOR = "#f39c12"  # orange -- KPI anomaly but no alarm yet
NORMAL_COLOR = "#5dade2"  # light blue -- healthy, shown only for topology context
ROOT_CAUSE_COLOR = "#f1c40f"  # gold -- the diagnosed root cause
EDGE_COLOR = "#94a3b8"


def build_subgraph_html(subgraph, root_cause_device=None, height="480px"):
    """Return a self-contained HTML string (all JS inlined) rendering
    `subgraph` (as returned by src.graphrag.retriever.retrieve_subgraph) as
    an interactive node/edge diagram: devices are nodes, DEPENDS_ON edges
    point from child to parent, alarmed/KPI-anomalous/diagnosed devices are
    colour-coded.
    """
    net = Network(height=height, width="100%", directed=True, bgcolor="#0f172a", font_color="#e2e8f0", cdn_resources="in_line")
    net.barnes_hut(gravity=-8000, spring_length=150, spring_strength=0.02)

    alarms_by_device = {}
    for a in subgraph["alarms"]:
        alarms_by_device.setdefault(a["device_id"], []).append(a["type"])
    kpi_ids = {k["device_id"] for k in subgraph["kpis"]}
    seed_ids = set(subgraph["seed_devices"])
    device_ids = {d["id"] for d in subgraph["devices"]}

    for d in subgraph["devices"]:
        dev_id = d["id"]
        if dev_id == root_cause_device:
            color = ROOT_CAUSE_COLOR
            shape = "star"
            size = 34
        elif dev_id in alarms_by_device:
            color = ALARM_COLOR
            shape = "dot"
            size = 24
        elif dev_id in kpi_ids:
            color = KPI_ONLY_COLOR
            shape = "dot"
            size = 22
        else:
            color = NORMAL_COLOR
            shape = "dot"
            size = 16

        title_lines = [f"{dev_id} (loai: {d['type']})"]
        if dev_id in alarms_by_device:
            title_lines.append("Alarm: " + ", ".join(alarms_by_device[dev_id]))
        if dev_id in kpi_ids:
            title_lines.append("Co KPI bat thuong")
        if dev_id in seed_ids:
            title_lines.append("[DIEM_KHOI_PHAT cua su co]")
        if dev_id == root_cause_device:
            title_lines.append(">>> NGUYEN NHAN GOC RE duoc chan doan <<<")

        net.add_node(
            dev_id,
            label=dev_id,
            title="\n".join(title_lines),
            color=color,
            shape=shape,
            size=size,
            borderWidth=3 if dev_id in seed_ids else 1,
        )

    for d in subgraph["devices"]:
        for parent_id in d.get("parent_ids") or []:
            if parent_id in device_ids:
                net.add_edge(d["id"], parent_id, arrows="to", color=EDGE_COLOR)

    return net.generate_html(notebook=False)
