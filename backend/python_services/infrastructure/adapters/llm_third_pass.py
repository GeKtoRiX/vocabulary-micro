from __future__ import annotations

import json
import re
import socket
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.domain.services import TextProcessor
from infrastructure.config import PipelineSettings


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_TEXT_PROCESSOR = TextProcessor()


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
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract English phrasal verbs and idioms from text. "
                        "Return strict JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self._settings.third_pass_llm_max_tokens > 0:
            payload["max_tokens"] = int(self._settings.third_pass_llm_max_tokens)

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
        timeout_seconds = max(0.2, float(effective_timeout_ms) / 1000.0)
        request_timeouts: list[float] = [timeout_seconds]
        # Local models can be slow on hard prompts; widen timeout on retry.
        for fallback_timeout in (15.0, 120.0):
            if timeout_seconds < fallback_timeout and fallback_timeout not in request_timeouts:
                request_timeouts.append(fallback_timeout)

        def _post_chat_once(request_payload: dict[str, Any]) -> dict[str, Any] | list[Any]:
            request = urllib_request.Request(
                endpoint,
                data=json.dumps(request_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            raw_body = ""
            for attempt_idx, request_timeout in enumerate(request_timeouts):
                try:
                    with urllib_request.urlopen(request, timeout=request_timeout) as response:
                        raw_body = response.read().decode("utf-8", errors="replace")
                    break
                except urllib_error.HTTPError as exc:
                    error_payload = ""
                    try:
                        error_payload = exc.read().decode("utf-8", errors="replace").strip()
                    except Exception:
                        error_payload = ""
                    details = f"{exc}"
                    if error_payload:
                        details = f"{details} | payload: {error_payload}"
                    raise RuntimeError(f"Failed to call LLM endpoint '{endpoint}': {details}") from exc
                except (urllib_error.URLError, TimeoutError, socket.timeout) as exc:
                    message = str(exc).lower()
                    is_timeout = (
                        isinstance(exc, (TimeoutError, socket.timeout))
                        or "timed out" in message
                        or "timeout" in message
                    )
                    if is_timeout and attempt_idx < len(request_timeouts) - 1:
                        continue
                    raise RuntimeError(f"Failed to call LLM endpoint '{endpoint}': {exc}") from exc
            return json.loads(raw_body)

        def _extract_parsed_payload(outer_payload: dict[str, Any]) -> tuple[dict[str, Any] | list[Any] | None, str]:
            choices = outer_payload.get("choices")
            if not isinstance(choices, list) or not choices:
                return None, ""
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message", {}) if isinstance(first, dict) else {}
            content = message.get("content") if isinstance(message, dict) else ""
            parsed = self._parse_content_payload(content)
            finish_reason = str(first.get("finish_reason", "")).strip().lower() if isinstance(first, dict) else ""
            return parsed, finish_reason

        outer = _post_chat_once(payload)
        if isinstance(outer, dict):
            parsed, finish_reason = _extract_parsed_payload(outer)
            if parsed is not None:
                return parsed
            # If output was cut by max_tokens, retry once with a larger completion budget.
            if finish_reason == "length":
                current_max_tokens = int(payload.get("max_tokens", 0) or 0)
                if current_max_tokens > 0:
                    retry_max_tokens = min(max(current_max_tokens * 2, current_max_tokens + 256), 4096)
                    if retry_max_tokens > current_max_tokens:
                        retry_payload = dict(payload)
                        retry_payload["max_tokens"] = retry_max_tokens
                        retry_outer = _post_chat_once(retry_payload)
                        if isinstance(retry_outer, dict):
                            retry_parsed, _ = _extract_parsed_payload(retry_outer)
                            if retry_parsed is not None:
                                return retry_parsed
                        outer = retry_outer
            return outer
        if isinstance(outer, list):
            return outer
        raise ValueError("LLM response payload must be an object or array")

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
            "Extract only explicit English phrasal verbs and idioms from the text.\n"
            "Rules:\n"
            "- Keep canonical form in lowercase.\n"
            "- expression_type must be only 'phrasal_verb' or 'idiom'.\n"
            "- usage_label must be 'idiomatic' unless clearly literal.\n"
            "- Do not invent phrases that are not present.\n"
            f"- Return at most {max_items} occurrences.\n"
            "- Keep gloss concise (max 12 words).\n"
            "- Return JSON object with key 'occurrences'.\n"
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

