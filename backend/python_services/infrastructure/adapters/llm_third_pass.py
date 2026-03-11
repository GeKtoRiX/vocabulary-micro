from __future__ import annotations

import json
import re
import socket
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from backend.python_services.core.domain.services import TextProcessor
from backend.python_services.infrastructure.config import PipelineSettings


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_CODE_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_JSON_OCCURRENCE_RE = re.compile(
    r'"canonical_form"\s*:\s*"(?P<form>[^"]+)"'
    r'(?:(?!canonical_form).)*?"expression_type"\s*:\s*"(?P<type>phrasal_verb|idiom)"'
    r'(?:(?!canonical_form).)*?"usage_label"\s*:\s*"(?P<usage>idiomatic|literal)"'
    r'(?:(?!canonical_form).)*?"gloss"\s*:\s*"(?P<gloss>[^"]*)"'
    r'(?:(?!canonical_form).)*?"confidence"\s*:\s*(?P<confidence>\d+(?:\.\d+)?)',
    re.DOTALL | re.IGNORECASE,
)
_TEXT_PROCESSOR = TextProcessor()
_SYSTEM_PROMPT = (
    "You are a conservative extractor of English phrasal verbs and idioms. "
    "Detect only explicit occurrences supported by the input text. "
    "Classify carefully between phrasal_verb and idiom. "
    "Return exactly one JSON object and nothing else."
)


def _normalize_expression_type(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"phrasal_verb", "phrasal"}:
        return "phrasal_verb"
    if value in {"idiom", "idiomatic"}:
        return "idiom"
    return ""


def _normalize_usage_label(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value == "literal":
        return "literal"
    return "idiomatic"


def _normalize_form(raw: str, *, expression_type: str = "") -> str:
    return _TEXT_PROCESSOR.canonicalize_expression(
        raw,
        expression_type=expression_type,
    )


class LlmThirdPassExtractor:
    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings

    def detect(
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None = None,
        enabled: bool | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        effective_enabled = (
            self._settings.enable_third_pass_llm
            if enabled is None
            else bool(enabled)
        )
        if not effective_enabled:
            return self._default_summary(
                enabled=False,
                status="skipped",
                reason="third_pass_disabled",
            )
        if not str(text or "").strip():
            return self._default_summary(
                enabled=True,
                status="skipped",
                reason="empty_text",
            )

        stage_start = time.perf_counter()
        stage_status: dict[str, Any] = {
            "stage": "llm_extract",
            "status": "ok",
            "reason": "",
            "duration_ms": 0.0,
                "metadata": {
                    "request_id": request_id,
                    "endpoint": self._settings.third_pass_llm_base_url,
                    "model": self._settings.third_pass_llm_model,
                    "think_mode": (
                        self._settings.third_pass_llm_think_mode
                        if think_mode is None
                        else bool(think_mode)
                    ),
                    "timeout_ms": (
                        int(timeout_ms)
                        if timeout_ms is not None
                        else int(self._settings.third_pass_llm_timeout_ms)
                    ),
                },
            }
        try:
            payload = self._request_llm(text=text, think_mode=think_mode, timeout_ms=timeout_ms)
            occurrences = self._normalize_occurrences(payload)
            if self._settings.third_pass_llm_max_items > 0:
                occurrences = occurrences[: int(self._settings.third_pass_llm_max_items)]
            status = "ok"
            reason = ""
        except Exception as exc:
            occurrences = []
            status = "failed"
            reason = "third_pass_request_failed"
            stage_status["status"] = "failed"
            stage_status["reason"] = reason
            stage_status.setdefault("metadata", {})
            if isinstance(stage_status["metadata"], dict):
                stage_status["metadata"]["error"] = str(exc)

        duration_ms = (time.perf_counter() - stage_start) * 1000.0
        stage_status["duration_ms"] = round(duration_ms, 3)
        summary = self._default_summary(
            enabled=True,
            status=status,
            reason=reason,
        )
        summary["occurrences"] = occurrences
        summary["candidates_count"] = len(occurrences)
        summary["resolved_count"] = len(occurrences)
        summary["uncertain_count"] = 0
        summary["stage_statuses"] = [stage_status]
        return summary

    def _request_llm(
        self,
        *,
        text: str,
        think_mode: bool | None,
        timeout_ms: int | None,
    ) -> dict[str, Any] | list[Any]:
        prompt = self._build_prompt(text=text, think_mode=think_mode)
        payload: dict[str, Any] = {
            "model": self._settings.third_pass_llm_model,
            "temperature": 0.0,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self._settings.third_pass_llm_max_tokens > 0:
            payload["max_tokens"] = int(self._settings.third_pass_llm_max_tokens)

        # chat_template_kwargs управляет режимом рассуждений в llama.cpp и vLLM.
        # /no_think в промпте — вторичный fallback для серверов без этого параметра.
        effective_think = (
            self._settings.third_pass_llm_think_mode
            if think_mode is None
            else bool(think_mode)
        )
        payload["chat_template_kwargs"] = {"enable_thinking": effective_think}

        endpoint = self._build_endpoint()
        headers = {"Content-Type": "application/json"}
        api_key = str(self._settings.third_pass_llm_api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        effective_timeout_ms = (
            int(timeout_ms)
            if timeout_ms is not None
            else int(self._settings.third_pass_llm_timeout_ms)
        )
        # Таймаут на каждый SSE-чанк (не на весь запрос).
        # На GPU токены приходят быстро; 30 с — достаточно даже для TTFT.
        chunk_timeout = max(15.0, min(float(effective_timeout_ms) / 1000.0, 30.0))

        request = urllib_request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            with urllib_request.urlopen(request, timeout=chunk_timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta") or {}
                    c = delta.get("content")
                    if c:
                        content_parts.append(c)
                    r = delta.get("reasoning_content")
                    if r:
                        reasoning_parts.append(r)
        except urllib_error.HTTPError as exc:
            error_payload = ""
            try:
                error_payload = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            details = f"{exc}"
            if error_payload:
                details = f"{details} | payload: {error_payload}"
            raise RuntimeError(f"Failed to call LLM endpoint '{endpoint}': {details}") from exc
        except (urllib_error.URLError, TimeoutError, socket.timeout) as exc:
            raise RuntimeError(f"Failed to call LLM endpoint '{endpoint}': {exc}") from exc

        content = "".join(content_parts)
        # Убираем блоки рассуждений Qwen3 (<think>...</think>) из контента.
        content_clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        parsed = self._parse_content_payload(content_clean or content)
        if parsed is None and reasoning_parts:
            parsed = self._parse_reasoning_payload("".join(reasoning_parts))
        if parsed is None:
            raise ValueError(
                f"Could not parse LLM response from '{endpoint}'. "
                f"Content preview: {(content_clean or content)[:300]!r}"
            )
        return parsed

    def _build_endpoint(self) -> str:
        base = str(self._settings.third_pass_llm_base_url or "").strip().rstrip("/")
        if not base:
            raise ValueError("THIRD_PASS_LLM_BASE_URL must not be empty")
        if base.endswith("/v1/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _parse_content_payload(self, content: Any) -> dict[str, Any] | list[Any] | None:
        if isinstance(content, (dict, list)):
            return content
        text = str(content or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass
        match = _JSON_OBJECT_RE.search(text)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return None
        if isinstance(parsed, (dict, list)):
            return parsed
        return None

    def _parse_reasoning_payload(self, content: Any) -> dict[str, Any] | list[Any] | None:
        text = str(content or "").strip()
        if not text:
            return None

        for match in _JSON_CODE_BLOCK_RE.finditer(text):
            parsed = self._parse_content_payload(match.group(1))
            if parsed is not None:
                return parsed

        json_like_occurrences = self._parse_reasoning_json_occurrences(text)
        if json_like_occurrences:
            return {"occurrences": json_like_occurrences}

        candidate_occurrences = self._parse_reasoning_candidate_blocks(text)
        if candidate_occurrences:
            return {"occurrences": candidate_occurrences}
        return None

    def _parse_reasoning_json_occurrences(self, text: str) -> list[dict[str, Any]]:
        occurrences: list[dict[str, Any]] = []
        for match in _JSON_OCCURRENCE_RE.finditer(text):
            occurrences.append(
                {
                    "canonical_form": match.group("form"),
                    "expression_type": match.group("type"),
                    "usage_label": match.group("usage"),
                    "gloss": match.group("gloss"),
                    "confidence": float(match.group("confidence")),
                }
            )
        return occurrences

    def _parse_reasoning_candidate_blocks(self, text: str) -> list[dict[str, Any]]:
        occurrences: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        def finalize_current() -> None:
            nonlocal current
            if current is None:
                return
            if current.get("canonical_form") and current.get("expression_type"):
                current.setdefault("usage_label", "idiomatic")
                current.setdefault("confidence", 0.9)
                current.setdefault("gloss", "")
                occurrences.append(dict(current))
            current = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            header_match = re.match(r'^[*-]\s*"(?P<form>[^"]+)"\s*:\s*(?P<desc>.*)$', line)
            if header_match is not None:
                finalize_current()
                description = header_match.group("desc").strip()
                current = {
                    "canonical_form": header_match.group("form").strip(),
                    "expression_type": self._infer_expression_type_from_text(description),
                    "usage_label": "idiomatic",
                    "gloss": self._extract_gloss_from_text(description),
                }
                continue

            if current is None:
                continue

            normalized_line = re.sub(r"^[*-]\s*", "", line).strip()
            lowered = normalized_line.lower()
            if re.match(r"^\d+\.", lowered):
                finalize_current()
                continue
            if lowered.startswith("type:"):
                current["expression_type"] = _normalize_expression_type(normalized_line.split(":", 1)[1])
                continue
            if lowered.startswith("usage:"):
                current["usage_label"] = _normalize_usage_label(normalized_line.split(":", 1)[1])
                continue
            if lowered.startswith("gloss:"):
                current["gloss"] = self._clean_reasoning_phrase(normalized_line.split(":", 1)[1])
                continue
            if lowered.startswith("confidence:"):
                current["confidence"] = self._normalize_reasoning_confidence(normalized_line.split(":", 1)[1])
                continue

        finalize_current()
        return occurrences

    def _infer_expression_type_from_text(self, text: str) -> str:
        lowered = str(text or "").strip().lower()
        if "phrasal verb" in lowered:
            return "phrasal_verb"
        if "idiom" in lowered:
            return "idiom"
        return ""

    def _extract_gloss_from_text(self, text: str) -> str:
        lowered = str(text or "").strip()
        meaning_match = re.search(r"meaning(?:\s+to)?\s+(.+)$", lowered, re.IGNORECASE)
        if meaning_match is None:
            return ""
        return self._clean_reasoning_phrase(meaning_match.group(1))

    def _clean_reasoning_phrase(self, text: str) -> str:
        cleaned = str(text or "").strip().strip(".").strip()
        return re.sub(r"\s+", " ", cleaned)

    def _normalize_reasoning_confidence(self, raw: str) -> float:
        value = self._clean_reasoning_phrase(raw).lower()
        try:
            return float(value)
        except ValueError:
            pass
        if value.startswith("high"):
            return 0.95
        if value.startswith("medium"):
            return 0.75
        if value.startswith("low"):
            return 0.55
        return 0.9

    def _build_prompt(self, *, text: str, think_mode: bool | None = None) -> str:
        effective_think = (
            self._settings.third_pass_llm_think_mode
            if think_mode is None
            else bool(think_mode)
        )
        think_prefix = "/think" if effective_think else "/no_think"
        max_items = max(1, int(self._settings.third_pass_llm_max_items))
        return (
            f"{think_prefix}\n"
            "Task: extract only explicit English phrasal verbs and idioms that actually occur in TEXT.\n"
            "Definitions:\n"
            "- phrasal_verb = a verb-headed multi-word expression whose verb + particle/preposition "
            "belong to the lexical unit. Canonicalize to dictionary form with the base verb and without "
            "inserted objects: \"came up with\" -> \"come up with\", \"let them down\" -> \"let down\".\n"
            "- idiom = a fixed or semi-fixed figurative expression whose overall meaning is not fully "
            "compositional. Canonicalize to common dictionary form: \"bitten off more than she could chew\" "
            "-> \"bite off more than one can chew\", \"called it a day\" -> \"call it a day\".\n"
            "Reject:\n"
            "- ordinary literal verb + preposition combinations;\n"
            "- free collocations or transparent combinations;\n"
            "- single words;\n"
            "- phrases not explicitly supported by the text.\n"
            "Decision policy:\n"
            "- If a candidate could fit both labels, use phrasal_verb only when it is clearly verb-headed "
            "and the particle/preposition is integral to the lexical unit.\n"
            "- Use idiom only for fixed figurative expressions.\n"
            "- If unsure, omit the candidate.\n"
            "Output rules:\n"
            "- Preserve the order of first appearance.\n"
            "- Keep canonical_form in lowercase.\n"
            "- expression_type must be only 'phrasal_verb' or 'idiom'.\n"
            "- usage_label must be 'idiomatic' unless the context is clearly literal.\n"
            "- confidence must be a number between 0.0 and 1.0.\n"
            f"- Return at most {max_items} occurrences.\n"
            "- Keep gloss concise (max 12 words).\n"
            "- Return exactly one JSON object with key 'occurrences'. No markdown. No commentary. No reasoning.\n"
            "- If there are no valid candidates, return {\"occurrences\": []}.\n"
            "JSON shape:\n"
            "{\n"
            "  \"occurrences\": [\n"
            "    {\n"
            "      \"canonical_form\": \"string\",\n"
            "      \"expression_type\": \"phrasal_verb|idiom\",\n"
            "      \"usage_label\": \"idiomatic|literal\",\n"
            "      \"gloss\": \"short meaning\",\n"
            "      \"confidence\": 0.0\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"TEXT:\n{text}"
        )

    def _normalize_occurrences(self, payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
        raw_items: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            raw_occ = payload.get("occurrences")
            if isinstance(raw_occ, list):
                raw_items.extend(item for item in raw_occ if isinstance(item, dict))
            phrasal = payload.get("phrasal_verbs")
            if isinstance(phrasal, list):
                for item in phrasal:
                    raw_items.append(
                        {
                            "canonical_form": item,
                            "expression_type": "phrasal_verb",
                            "usage_label": "idiomatic",
                        }
                    )
            idioms = payload.get("idioms")
            if isinstance(idioms, list):
                for item in idioms:
                    raw_items.append(
                        {
                            "canonical_form": item,
                            "expression_type": "idiom",
                            "usage_label": "idiomatic",
                        }
                    )
        elif isinstance(payload, list):
            raw_items.extend(item for item in payload if isinstance(item, dict))

        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            expression_type = _normalize_expression_type(item.get("expression_type", ""))
            if not expression_type:
                continue
            canonical = _normalize_form(
                item.get("canonical_form", ""),
                expression_type=expression_type,
            )
            if not canonical:
                continue
            marker = (canonical, expression_type)
            if marker in seen:
                continue
            seen.add(marker)
            confidence = item.get("confidence")
            try:
                score = float(confidence) if confidence is not None else 0.0
            except Exception:
                score = 0.0
            normalized.append(
                {
                    "surface": canonical,
                    "canonical_form": canonical,
                    "expression_type": expression_type,
                    "is_separable": False,
                    "span_start": 0,
                    "span_end": 0,
                    "sentence_text": "",
                    "sense": None,
                    "alternatives": [],
                    "score": score,
                    "margin": 0.0,
                    "usage_label": _normalize_usage_label(item.get("usage_label", "idiomatic")),
                    "status": "resolved",
                    "gloss": str(item.get("gloss", "")).strip(),
                }
            )
        return normalized

    def _default_summary(self, *, enabled: bool, status: str, reason: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "enabled": enabled,
            "status": status,
            "reason": reason,
            "model_info": {
                "provider": "openai_compatible",
                "base_url": self._settings.third_pass_llm_base_url,
                "model": self._settings.third_pass_llm_model,
                "timeout_ms": self._settings.third_pass_llm_timeout_ms,
            },
            "candidates_count": 0,
            "resolved_count": 0,
            "uncertain_count": 0,
            "occurrences": [],
            "stage_statuses": [],
            "cache_hit": False,
            "sync_enabled": False,
            "sync_stage_status": {
                "status": "skipped",
                "reason": "third_pass_not_synced",
                "duration_ms": 0.0,
            },
            "added": [],
            "already_existed": [],
            "queued_for_sync": [],
            "rejected_candidates": [],
            "category_review_required": [],
        }
