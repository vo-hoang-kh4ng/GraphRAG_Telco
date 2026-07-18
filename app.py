"""Streamlit web demo (mục 6/7 đề cương: "giao diện demo dạng web app đơn giản").

Chạy: streamlit run app.py
(Yêu cầu Neo4j đang chạy: docker compose up -d)
"""

import streamlit as st
import streamlit.components.v1 as components

from src.graphrag.context_builder import build_context_text
from src.graphrag.graph_viz import build_subgraph_html
from src.graphrag.llm_client import _parse_llm_json, get_llm_client
from src.graphrag.pipeline import GraphRAGResult
from src.graphrag.retriever import retrieve_subgraph
from src.kg import graph_builder
from src.kg.connection import Neo4jConnection
from src.kg.dejavu_data import DEVICES as DEJAVU_DEVICES
from src.kg.dejavu_data import INCIDENTS as DEJAVU_INCIDENTS
from src.kg.sample_data import SCENARIOS
from src.rules.rule_engine import run_rule_engine
from src.synthesis.combiner import combine, suggest_action

st.set_page_config(
    page_title="KG + GraphRAG + Rule-Based Reasoning - Chan doan su co",
    page_icon="🛰️",
    layout="wide",
)


@st.cache_resource
def get_connection():
    return Neo4jConnection()


def ensure_dataset_loaded(conn, dataset_key):
    if st.session_state.get("loaded_dataset") == dataset_key:
        return
    with st.spinner(f"Đang nạp topology ({dataset_key}) vào Neo4j..."):
        if dataset_key == "telecom":
            graph_builder.bootstrap(conn)
        else:
            graph_builder.bootstrap_devices_only(conn, DEJAVU_DEVICES)
    st.session_state["loaded_dataset"] = dataset_key


def render_diagnosis_tab(conn):
    dataset_label = st.radio(
        "Bộ dữ liệu",
        ["Viễn thông (mô phỏng, đề cương)", "DejaVu (dữ liệu thật, IT-ops - đối chiếu tổng quát hoá)"],
        horizontal=True,
    )
    is_telecom = dataset_label.startswith("Viễn thông")
    ensure_dataset_loaded(conn, "telecom" if is_telecom else "dejavu")

    incidents = SCENARIOS if is_telecom else DEJAVU_INCIDENTS
    options = {inc["id"]: inc for inc in incidents}
    selected_id = st.selectbox(
        "Chọn sự cố",
        list(options.keys()),
        format_func=lambda x: f"{x} - {options[x]['name'][:80]}",
    )
    incident = options[selected_id]
    st.info(incident["description"])

    if incident.get("alarms") or incident.get("kpi_anomalies"):
        with st.expander("Cảnh báo / KPI đầu vào của kịch bản này", expanded=False):
            if incident.get("alarms"):
                st.write("**Alarms:**")
                st.dataframe(incident["alarms"], width="stretch")
            if incident.get("kpi_anomalies"):
                st.write("**KPI bất thường:**")
                st.dataframe(incident["kpi_anomalies"], width="stretch")

    run_clicked = st.button("🚀 Chạy chẩn đoán (Rule Engine + GraphRAG)", type="primary")

    if run_clicked:
        graph_builder.load_scenario(conn, incident)

        with st.spinner("Rule Engine đang suy diễn (IF-THEN)..."):
            rule_candidates = run_rule_engine(conn)

        with st.spinner("GraphRAG đang truy xuất subgraph..."):
            subgraph = retrieve_subgraph(conn, incident["id"])
            context_text = build_context_text(subgraph)
            llm_client = get_llm_client()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("⚙️ Rule Engine (IF-THEN reasoning)")
            if rule_candidates:
                st.dataframe(
                    [
                        {"Thiết bị": c.device_id, "Độ tin cậy (CF)": round(c.confidence, 2), "Luật kích hoạt": c.rule_id}
                        for c in rule_candidates
                    ],
                    width="stretch",
                )
                st.caption(rule_candidates[0].explanation)
            else:
                st.warning("Không có luật nào kích hoạt trên trạng thái hiện tại.")

        with col2:
            st.subheader("🕸️ GraphRAG (LLM diagnosis)")
            if getattr(llm_client, "supports_streaming", False):
                st.caption(f"⏺️ Đang nhận token trực tiếp từ {type(llm_client).__name__} (streaming thật)...")
                stream_box = st.empty()
                raw_text = ""
                for chunk in llm_client.diagnose_stream(context_text, subgraph):
                    raw_text += chunk
                    stream_box.markdown(f"```\n{raw_text}▌\n```")
                stream_box.empty()
                with st.expander("Xem toàn bộ phản hồi thô (raw) từ LLM, đã stream xong"):
                    st.code(raw_text, language="markdown")
                diagnosis = _parse_llm_json(raw_text)
            else:
                with st.spinner(f"Đang hỏi {type(llm_client).__name__}..."):
                    diagnosis = llm_client.diagnose(context_text, subgraph)

            graphrag_result = GraphRAGResult(
                incident_id=incident["id"],
                subgraph=subgraph,
                context_text=context_text,
                root_cause_device=diagnosis.root_cause_device,
                confidence=diagnosis.confidence,
                explanation=diagnosis.explanation,
                citations=diagnosis.citations,
            )

            if graphrag_result.root_cause_device:
                st.metric(
                    "Nguyên nhân đề xuất bởi LLM",
                    graphrag_result.root_cause_device,
                    f"confidence = {graphrag_result.confidence:.2f}",
                )
            else:
                st.warning("GraphRAG không đưa ra được chẩn đoán (thiếu dữ liệu).")
            st.write(graphrag_result.explanation)

        ranked = combine(rule_candidates, graphrag_result)

        st.subheader("🗺️ Sơ đồ đồ thị con (subgraph) được GraphRAG truy xuất")
        st.caption(
            "🔴 thiết bị đang có alarm · 🟠 chỉ có KPI bất thường · 🟡 (ngôi sao) nguyên nhân gốc rễ được chẩn đoán "
            "· 🔵 thiết bị khác trong phạm vi topology · viền đậm = điểm khởi phát sự cố. Cạnh mũi tên = quan hệ "
            "phụ_thuộc_vào (DEPENDS_ON), hướng từ thiết bị con sang thiết bị cha."
        )
        top_device = ranked[0].device_id if ranked else None
        graph_html = build_subgraph_html(graphrag_result.subgraph, root_cause_device=top_device)
        components.html(graph_html, height=500, scrolling=False)

        with st.expander("Xem ngữ cảnh dạng văn bản gửi cho LLM"):
            st.code(graphrag_result.context_text, language="markdown")

        st.divider()
        st.subheader("✅ Khuyến nghị tổng hợp (Rule Engine + GraphRAG)")

        if ranked:
            top = ranked[0]
            action = suggest_action(top.device_id, graphrag_result.subgraph)
            agree_badge = "🤝 Rule Engine và GraphRAG đồng thuận" if top.agreement else "⚠️ Chỉ một nguồn ủng hộ"
            st.success(
                f"**Nguyên nhân gốc rễ: {top.device_id}**  \n"
                f"Độ tin cậy tổng hợp: **{top.combined_confidence:.2f}**  \n"
                f"Nguồn: {' + '.join(top.sources)} — {agree_badge}  \n\n"
                f"**Hướng xử lý đề xuất:** {action}"
            )
            st.dataframe(
                [
                    {
                        "Thiết bị": r.device_id,
                        "Độ tin cậy tổng hợp": round(r.combined_confidence, 2),
                        "Nguồn": " + ".join(r.sources),
                        "Đồng thuận": "✅" if r.agreement else "—",
                    }
                    for r in ranked
                ],
                width="stretch",
            )

            truth = incident["ground_truth_root_cause"]
            if top.device_id == truth:
                st.balloons()
                st.caption(f"✔️ Khớp với ground truth: {truth}")
            else:
                st.caption(f"✘ Ground truth thực tế là: {truth} (khác với kết quả hệ thống)")
        else:
            st.warning("Không có ứng viên nguyên nhân nào từ cả hai nguồn.")


def render_evaluation_tab(conn):
    st.write(
        "So sánh độ chính xác chẩn đoán giữa **chỉ Rule-based**, **chỉ GraphRAG**, và **kết hợp cả hai** "
        "(đúng yêu cầu mục 7 của đề cương)."
    )
    dataset_label = st.radio(
        "Bộ dữ liệu để đánh giá",
        ["Viễn thông (5 kịch bản mô phỏng)", "DejaVu (78 sự cố thật)"],
        horizontal=True,
        key="eval_dataset",
    )
    is_telecom = dataset_label.startswith("Viễn thông")

    if st.button("📊 Chạy đánh giá", type="primary"):
        ensure_dataset_loaded(conn, "telecom" if is_telecom else "dejavu")

        if is_telecom:
            from src.evaluation.evaluate import evaluate

            rows = evaluate(conn)
        else:
            from src.evaluation.evaluate_dejavu import evaluate

            with st.spinner("Đang chạy trên 78 sự cố thật (có thể mất một lúc)..."):
                rows = evaluate(conn)

        n = len(rows)
        col1, col2, col3 = st.columns(3)
        rule_acc = sum(1 for r in rows if r["rule_correct"]) / n
        graphrag_acc = sum(1 for r in rows if r["graphrag_correct"]) / n
        combined_acc = sum(1 for r in rows if r["combined_correct"]) / n
        col1.metric("Rule-only", f"{rule_acc:.0%}")
        col2.metric("GraphRAG-only", f"{graphrag_acc:.0%}")
        col3.metric("Combined", f"{combined_acc:.0%}")

        st.bar_chart(
            {"Rule-only": rule_acc, "GraphRAG-only": graphrag_acc, "Combined": combined_acc},
        )

        with st.expander(f"Chi tiết {n} kết quả"):
            st.dataframe(
                [
                    {
                        "ID": r["id"] if "id" in r else r["scenario"],
                        "Ground truth": r["truth"],
                        "Rule-only": r["rule_pred"],
                        "GraphRAG-only": r["graphrag_pred"],
                        "Combined": r["combined_pred"],
                        "Đúng?": "✅" if r["combined_correct"] else "❌",
                    }
                    for r in rows
                ],
                width="stretch",
            )


def main():
    st.title("🛰️ Hệ thống hỗ trợ phân tích và chẩn đoán sự cố hệ thống mạng và dịch vụ CNTT")
    st.caption(
        "Knowledge Graph + Rule-Based Reasoning + GraphRAG — demo học phần Biểu diễn tri thức và ứng dụng "
        "(Cao học, Học viện Ngân hàng)"
    )

    try:
        conn = get_connection()
        conn.verify_connectivity()
    except Exception as e:
        st.error(
            "Không kết nối được Neo4j. Hãy chạy `docker compose up -d` rồi tải lại trang.\n\n"
            f"Chi tiết lỗi: {e}"
        )
        st.stop()

    tab1, tab2 = st.tabs(["🔍 Chẩn đoán trực tiếp", "📊 Đánh giá tổng thể"])
    with tab1:
        render_diagnosis_tab(conn)
    with tab2:
        render_evaluation_tab(conn)


if __name__ == "__main__":
    main()
