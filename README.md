# GraphRAG_Telco

Prototype cho đề tài tiểu luận **"Hệ thống hỗ trợ phân tích và chẩn đoán sự cố mạng viễn thông sử dụng Knowledge Graph, GraphRAG và Rule-Based Reasoning"** (học phần Biểu diễn tri thức và ứng dụng).

## Kiến trúc (bám theo mục 6 của đề cương)

```
src/
  kg/          Lớp dữ liệu + Knowledge Graph (Neo4j): schema, sample data, graph_builder
  rules/       Module suy diễn luật (Rule Engine, IF-THEN, certainty-factor combination)
  graphrag/    Module GraphRAG: retriever (subgraph) -> context_builder (text) -> llm_client -> pipeline
  synthesis/   Module tổng hợp: kết hợp Rule Engine + GraphRAG, xếp hạng, đề xuất hướng xử lý
  evaluation/  So sánh độ chính xác: rule-only vs GraphRAG-only vs combined
  demo.py      CLI demo end-to-end trên từng kịch bản sự cố mẫu
tests/         Unit test cho rule engine, context builder, mock LLM, combiner (chạy không cần Neo4j)
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
