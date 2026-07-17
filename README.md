# GraphRAG_Telco

Prototype cho đề tài tiểu luận **"Hệ thống hỗ trợ phân tích và chẩn đoán sự cố mạng viễn thông sử dụng Knowledge Graph, GraphRAG và Rule-Based Reasoning"** (học phần Biểu diễn tri thức và ứng dụng).

## Kiến trúc (bám theo mục 6 của đề cương)

```
src/
  kg/          Lớp dữ liệu + Knowledge Graph (Neo4j): schema, sample data, dejavu_data, graph_builder
  rules/       Module suy diễn luật (Rule Engine, IF-THEN, certainty-factor combination, topology dạng DAG đa-cha)
  graphrag/    Module GraphRAG: retriever (subgraph) -> context_builder (text) -> llm_client -> pipeline
  synthesis/   Module tổng hợp: kết hợp Rule Engine + GraphRAG, xếp hạng, đề xuất hướng xử lý
  evaluation/  evaluate.py (kịch bản viễn thông giả lập) + evaluate_dejavu.py (dữ liệu THẬT, xem mục bên dưới)
  demo.py      CLI demo end-to-end trên từng kịch bản sự cố mẫu
scripts/       fetch_dejavu.py -- tải + parse dữ liệu thật, tái tạo src/kg/dejavu_data.py
tests/         Unit test cho rule engine, context builder, mock LLM, combiner, dữ liệu DejaVu (chạy không cần Neo4j)
```

LLM mặc định là `MockLLM` (không cần API key, chạy offline hoàn toàn) — xem `src/graphrag/llm_client.py`. Có thể chuyển sang Anthropic/OpenAI thật bằng biến môi trường `LLM_PROVIDER`.

## Cài đặt

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # rồi chỉnh nếu cần
```

## Chạy Knowledge Graph (Neo4j)

```bash
docker compose up -d
```

Neo4j Browser: http://localhost:7474 (user `neo4j`, password `telco12345` — xem `docker-compose.yml` / `.env.example`).

## Chạy demo

```bash
python -m src.demo --list                 # liệt kê các kịch bản mẫu
python -m src.demo --scenario SCN-01       # chạy full pipeline: Rule Engine -> GraphRAG -> tổng hợp
```

Mỗi lần chạy sẽ in ra: cảnh báo/KPI của kịch bản, ứng viên nguyên nhân từ Rule Engine (kèm luật kích hoạt), ngữ cảnh subgraph được truy xuất cho GraphRAG, giải thích của LLM, và khuyến nghị cuối cùng sau khi tổng hợp hai nguồn.

## Đánh giá (so sánh 3 phương pháp)

```bash
python -m src.evaluation.evaluate
```

In bảng so sánh độ chính xác của rule-only / GraphRAG-only / combined trên toàn bộ `SCENARIOS` (đúng như yêu cầu mục 7 của đề cương).

## Dữ liệu thật: hành trình và đánh đổi

Đề cương giới hạn phạm vi ở dữ liệu mô phỏng (không đụng dữ liệu vận hành thật đang bảo mật), nhưng dự án có thử tìm dữ liệu thật để đối chiếu độc lập:

1. **NetRCA** (ICASSP 2022 AIOps Challenge, alarm/KPI 5G thật kèm causal graph) — khớp nhất về use case, nhưng **hạ tầng đã chết**: trang challenge không resolve DNS, không tìm được bản mirror dữ liệu ở đâu khác.
2. **TeleLogs** (Hugging Face `netop/TeleLogs`, Huawei) — hạ tầng còn sống, nhưng bị **gate thủ công** (phải xin quyền, chờ duyệt) và chính dataset card **cấm redistribute** — không hợp để cache/commit vào repo public cho một bài tiểu luận.
3. **NetManAIOps/DejaVu** (Zenodo, DOI [10.5281/zenodo.6955909](https://zenodo.org/records/6955909), CC-BY 4.0) — dùng được: tải thẳng không cần đăng nhập, license cho phép redistribute, và có cấu trúc **đồ thị phụ thuộc thật + fault injection thật + ground-truth root cause thật**. Đây là dữ liệu đã tích hợp, xem `src/kg/dejavu_data.py`.

**Đánh đổi cần nói rõ:** DejaVu là dữ liệu hạ tầng IT-ops/microservice thật (Docker/DB/OS gọi lẫn nhau), **không phải dữ liệu viễn thông**. Nó được dùng vì có cùng bản chất đồ thị-lý-thuyết (dependency graph + lan truyền lỗi + định vị nguyên nhân gốc) với bài toán viễn thông, nên là một phép kiểm tra tổng quát hoá hợp lệ — không phải một bộ dữ liệu viễn thông thay thế. Toàn bộ 78 sự cố thật trong dataset này đều là lỗi đơn-thiết-bị (không có case cascade multi-alarm), khác với 5 kịch bản viễn thông giả lập vốn được thiết kế riêng để kiểm tra suy luận cascade nhiều tầng.

Topology thật của DejaVu cũng là **DAG đa-cha** (một container có thể phụ thuộc nhiều database/container khác + host của nó cùng lúc) chứ không phải cây đơn-cha như topology viễn thông giả lập — Rule Engine và GraphRAG đã được tổng quát hoá để hỗ trợ nhiều-cha (xem `parents_of` trong `src/rules/rule_engine.py`), một cải tiến hợp lý ngay cả cho mạng viễn thông thật (redundancy, dual-homing).

```bash
python -m src.evaluation.evaluate_dejavu   # đánh giá trên 78 su co that, bang rieng, khong gop voi bang tren
```

## Chạy test (không cần Neo4j)

```bash
pytest tests/ -v
```

Các test dựng `facts` / `subgraph` trực tiếp từ dữ liệu mẫu (`src/kg/sample_data.py`) nên không phụ thuộc vào Neo4j đang chạy hay không.

## Dùng LLM thật thay cho MockLLM

Trong `.env`:

```
LLM_PROVIDER=anthropic        # hoặc openai
ANTHROPIC_API_KEY=sk-ant-...
```

Không cần sửa code — `src/graphrag/llm_client.get_llm_client()` sẽ tự chọn client theo `LLM_PROVIDER`.
