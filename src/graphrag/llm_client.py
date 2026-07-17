"""Pluggable LLM client for the GraphRAG explanation step (section 5.2, step 3).

`MockLLM` is the default: it needs no API key and reasons directly over the
retrieved subgraph using (1) case-based matching against historical
incidents and (2) simple structural heuristics on the dependency graph -- a
stand-in for what a real LLM would infer from the same structured text
context. `AnthropicLLM` / `OpenAILLM` send the exact same context text to a
real model and are selected by setting LLM_PROVIDER in the environment; no
other code in the pipeline needs to change to swap between them.
"""

import json
import os
import re
from dataclasses import dataclass, field

from src.kg.sample_data import HISTORICAL_INCIDENTS

SIGNAL_LOSS_ALARM_TYPES = {"LOSS_OF_SIGNAL", "CELL_DOWN", "LOW_THROUGHPUT"}
SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1, "warning": 0}
CASE_MATCH_JACCARD_THRESHOLD = 0.5

DIAGNOSTIC_QUESTION = (
    "Dua tren ngu canh Knowledge Graph ben duoi, hay xac dinh thiet bi nao la NGUYEN NHAN GOC RE "
    "(root cause) cua su co, va giai thich ngan gon ly do. CHI tra loi bang MOT doi tuong JSON hop le, "
    "khong them bat ky van ban, giai thich hay markdown nao khac ngoai JSON. JSON phai co dung cac "
    'truong: root_cause_device (string), confidence (so thuc 0-1), explanation (string). '
    'Vi du dinh dang: {"root_cause_device": "docker_003", "confidence": 0.8, "explanation": "..."}'
)


@dataclass
class LLMDiagnosis:
    root_cause_device: str | None
    confidence: float
    explanation: str
    citations: list = field(default_factory=list)


class LLMClient:
    def diagnose(self, context_text, subgraph) -> LLMDiagnosis:
        raise NotImplementedError


class MockLLM(LLMClient):
    """Offline stand-in LLM. Reasons over `subgraph` directly; ignores nothing
    from `context_text` conceptually -- it is the same information, just not
    re-parsed from prose since no real model call happens here.
    """

    def diagnose(self, context_text, subgraph):
        alarmed_devices = {a["device_id"] for a in subgraph["alarms"]}
        parents_by_device = {d["id"]: (d.get("parent_ids") or []) for d in subgraph["devices"]}

        case_match = self._match_historical_case(alarmed_devices)
        if case_match:
            return case_match

        if alarmed_devices:
            structural = self._structural_diagnosis(alarmed_devices, parents_by_device, subgraph["alarms"])
            if structural:
                return structural

        return self._kpi_fallback(subgraph["kpis"])

    def _match_historical_case(self, alarmed_devices):
        if not alarmed_devices:
            return None
        best = None
        best_score = 0.0
        for hist in HISTORICAL_INCIDENTS:
            affected = set(hist["affected_devices"])
            if hist["root_cause_device"] not in alarmed_devices:
                continue
            intersection = alarmed_devices & affected
            union = alarmed_devices | affected
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard > best_score:
                best_score = jaccard
                best = hist
        if best and best_score >= CASE_MATCH_JACCARD_THRESHOLD:
            return LLMDiagnosis(
                root_cause_device=best["root_cause_device"],
                confidence=round(0.75 + 0.15 * best_score, 4),
                explanation=(
                    f"Mau canh bao hien tai giong {round(best_score * 100)}% voi su co lich su "
                    f"{best['id']} ({best['title']}), trong do nguyen nhan goc re da duoc xac nhan la "
                    f"{best['root_cause_device']}. Tom tat case cu: {best['summary']}"
                ),
                citations=[best["id"]],
            )
        return None

    def _structural_diagnosis(self, alarmed_devices, parents_by_device, alarms):
        # Devices with NO alarmed parent (possibly several parents -- topology is a
        # DAG) -- the topmost alarmed node(s) in the dependency chain.
        root_candidates = [
            d for d in alarmed_devices if not (set(parents_by_device.get(d, [])) & alarmed_devices)
        ]

        if len(root_candidates) == 1:
            dev = root_candidates[0]
            descendants_alarmed = [d for d in alarmed_devices if d != dev]
            if descendants_alarmed:
                return LLMDiagnosis(
                    root_cause_device=dev,
                    confidence=0.8,
                    explanation=(
                        f"{dev} la thiet bi cao nhat trong chuoi phu thuoc dang phat canh bao; cac thiet bi "
                        f"phia duoi ({', '.join(descendants_alarmed)}) cung dang gap su co tuong ung -> "
                        f"nhieu kha nang {dev} la nguon goc gay ra hieu ung day chuyen."
                    ),
                    citations=[],
                )
            return LLMDiagnosis(
                root_cause_device=dev,
                confidence=0.7,
                explanation=(
                    f"{dev} la thiet bi duy nhat phat canh bao trong pham vi tieu do thi, khong co bang "
                    f"chung lan truyen len thiet bi cha hay xuong thiet bi con -> su co co ve khu tru tai {dev}."
                ),
                citations=[],
            )

        if len(root_candidates) >= 2:
            common_parents = None
            for d in root_candidates:
                pset = set(parents_by_device.get(d, []))
                common_parents = pset if common_parents is None else (common_parents & pset)
            if common_parents:
                shared_parent = sorted(common_parents)[0]
                return LLMDiagnosis(
                    root_cause_device=shared_parent,
                    confidence=0.65,
                    explanation=(
                        f"Nhieu thiet bi ({', '.join(root_candidates)}) cung phat canh bao va cung phu "
                        f"thuoc vao {shared_parent}, du {shared_parent} chua co canh bao tuong minh -> nghi "
                        f"ngo {shared_parent} la diem loi chung."
                    ),
                    citations=[],
                )
            best = max(root_candidates, key=lambda d: max(
                (SEVERITY_RANK.get(a["severity"], 0) for a in alarms if a["device_id"] == d), default=0
            ))
            return LLMDiagnosis(
                root_cause_device=best,
                confidence=0.6,
                explanation=(
                    f"Co nhieu ({len(root_candidates)}) thiet bi cung phat canh bao doc lap nhau; {best} "
                    f"duoc chon do co muc do canh bao cao nhat trong so cac ung vien."
                ),
                citations=[],
            )
        return None

    def _kpi_fallback(self, kpis):
        if not kpis:
            return LLMDiagnosis(root_cause_device=None, confidence=0.0, explanation="Khong du du lieu de chan doan.")
        status_rank = {"critical": 2, "warning": 1}
        worst = max(kpis, key=lambda k: status_rank.get(k["status"], 0))
        return LLMDiagnosis(
            root_cause_device=worst["device_id"],
            confidence=0.55,
            explanation=(
                f"Chua co canh bao chinh thuc nao duoc sinh ra, nhung {worst['device_id']} co KPI "
                f"{worst['name']}={worst['value']} o trang thai {worst['status']} -> nghi ngo thiet bi nay "
                f"dang suy giam hieu nang (early warning)."
            ),
            citations=[],
        )


class AnthropicLLM(LLMClient):
    def __init__(self, model="claude-sonnet-5"):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("pip install anthropic to use LLM_PROVIDER=anthropic") from e
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def diagnose(self, context_text, subgraph):
        message = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": f"{context_text}\n\n{DIAGNOSTIC_QUESTION}"}],
        )
        return _parse_llm_json(message.content[0].text)


class OpenAILLM(LLMClient):
    def __init__(self, model="gpt-4o-mini"):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("pip install openai to use LLM_PROVIDER=openai") from e
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def diagnose(self, context_text, subgraph):
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": f"{context_text}\n\n{DIAGNOSTIC_QUESTION}"}],
        )
        return _parse_llm_json(response.choices[0].message.content)


class GroqLLM(LLMClient):
    def __init__(self, model="llama-3.3-70b-versatile"):
        try:
            from groq import Groq
        except ImportError as e:
            raise RuntimeError("pip install groq to use LLM_PROVIDER=groq") from e
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=api_key)
        self._model = model

    def diagnose(self, context_text, subgraph):
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": f"{context_text}\n\n{DIAGNOSTIC_QUESTION}"}],
        )
        return _parse_llm_json(response.choices[0].message.content)


def _extract_json_object(raw_text):
    """Real LLMs (esp. smaller/open models via Groq) often wrap the JSON answer
    in prose reasoning and/or a ```json fenced block instead of returning pure
    JSON. Try, in order: a fenced ```json block anywhere in the text, then the
    outermost {...} span, then the raw text as-is.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    brace_span = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if brace_span:
        return brace_span.group(0)
    return raw_text.strip()


def _parse_llm_json(raw_text):
    data = json.loads(_extract_json_object(raw_text))
    return LLMDiagnosis(
        root_cause_device=data.get("root_cause_device"),
        confidence=float(data.get("confidence", 0.0)),
        explanation=data.get("explanation", ""),
        citations=data.get("citations", []),
    )


def get_llm_client():
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider == "mock":
        return MockLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "openai":
        return OpenAILLM()
    if provider == "groq":
        return GroqLLM()
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
