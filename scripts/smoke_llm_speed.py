#!/usr/bin/env python3
"""
Smoke-тест LLM third-pass: скорость генерации + корректность извлечения.

Запуск (стек должен быть поднят через ./start.sh):
    python3 scripts/smoke_llm_speed.py
    python3 scripts/smoke_llm_speed.py --llm-only   # только LLM endpoint, без gateway
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from urllib import request as urllib_request

# C1-текст с фразовыми глаголами и идиомами
TEST_SENTENCES = [
    (
        "She decided to put off the meeting because she had bitten off more than she could chew, "
        "and the project was about to fall apart unless someone stepped up.",
        {"put off", "bite off more than one can chew", "fall apart", "step up"},
    ),
    (
        "He managed to pull through the crisis, but his colleagues felt he had let them down "
        "by not coming up with a contingency plan sooner.",
        {"pull through", "let down", "come up with"},
    ),
]
DIRECT_SYSTEM_PROMPT = (
    "You are a conservative extractor of English phrasal verbs and idioms. "
    "Detect only explicit occurrences supported by the input text. "
    "Classify carefully between phrasal_verb and idiom. "
    "Return exactly one JSON object and nothing else."
)


def build_direct_prompt(text: str) -> str:
    return (
        "/no_think\n"
        "Task: extract only explicit English phrasal verbs and idioms that actually occur in TEXT.\n"
        "Definitions:\n"
        "- phrasal_verb = a verb-headed multi-word expression whose verb + particle/preposition "
        "belong to the lexical unit. Canonicalize to dictionary form with the base verb and without "
        "inserted objects: \"came up with\" -> \"come up with\", \"let them down\" -> \"let down\".\n"
        "- idiom = a fixed or semi-fixed figurative expression whose overall meaning is not fully "
        "compositional. Canonicalize to common dictionary form: \"bitten off more than she could chew\" "
        "-> \"bite off more than one can chew\", \"called it a day\" -> \"call it a day\".\n"
        "Reject ordinary literal verb + preposition combinations, free collocations, single words, "
        "and phrases not explicitly supported by the text.\n"
        "If a candidate could fit both labels, use phrasal_verb only when it is clearly verb-headed "
        "and the particle/preposition is integral to the lexical unit. Use idiom only for fixed "
        "figurative expressions. If unsure, omit the candidate.\n"
        "Output rules:\n"
        "- Preserve order of first appearance.\n"
        "- Keep canonical_form in lowercase.\n"
        "- expression_type must be only 'phrasal_verb' or 'idiom'.\n"
        "- usage_label must be 'idiomatic' unless the context is clearly literal.\n"
        "- gloss <= 12 words.\n"
        "- confidence must be a number between 0.0 and 1.0.\n"
        "- Return exactly one JSON object with key 'occurrences'. No markdown. No commentary. No reasoning.\n"
        "- If there are no valid candidates, return {\"occurrences\": []}.\n"
        "JSON shape:\n"
        "{\"occurrences\": [{\"canonical_form\": \"string\", \"expression_type\": \"phrasal_verb|idiom\", "
        "\"usage_label\": \"idiomatic|literal\", \"gloss\": \"short meaning\", \"confidence\": 0.0}]}\n\n"
        f"TEXT:\n{text}"
    )


def http_get(url: str, timeout: float = 5.0) -> dict:
    req = urllib_request.Request(url)
    with urllib_request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def http_post(url: str, body: dict, timeout: float = 120.0) -> dict:
    data = json.dumps(body).encode()
    req = urllib_request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib_request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def llm_stream_chat(
    llm_url: str,
    messages: list[dict],
    model: str,
    think_mode: bool = False,
    max_tokens: int = 256,
    chunk_timeout: float = 30.0,
) -> tuple[str, str, float, int]:
    """Streaming POST к LLM.
    Возвращает (content, reasoning_content, секунды, число_всех_чанков).
    """
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": think_mode},
    }
    req = urllib_request.Request(
        f"{llm_url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    total_chunks = 0
    t0 = time.perf_counter()
    with urllib_request.urlopen(req, timeout=chunk_timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
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
                total_chunks += 1
            r = delta.get("reasoning_content")
            if r:
                reasoning_parts.append(r)
                total_chunks += 1
    elapsed = time.perf_counter() - t0
    return "".join(content_parts), "".join(reasoning_parts), elapsed, total_chunks


def consume_sse_job(gateway_url: str, text: str, timeout: float = 180.0) -> list[dict]:
    """POST /api/parse → читает SSE поток. Возвращает список событий."""
    body = {"text": text, "third_pass_enabled": True, "think_mode": False}
    job_resp = http_post(f"{gateway_url}/api/parse", body, timeout=10.0)
    job_id = job_resp.get("job_id")
    if not job_id:
        raise ValueError(f"No job_id in response: {job_resp}")

    stream_url = f"{gateway_url}/api/parse/jobs/{job_id}/stream"
    req = urllib_request.Request(stream_url)
    events: list[dict] = []
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
                events.append(ev)
                if ev.get("type") in {"done", "error"}:
                    break
            except json.JSONDecodeError:
                continue
    return events


def extract_llm_occurrences(events: list[dict]) -> list[dict]:
    """Достаёт occurrences только из llm_summary (не из NLP)."""
    for ev in events:
        if ev.get("type") == "stage_progress" and ev.get("stage") == "llm":
            llm_summary = ev.get("llm_summary") or {}
            return llm_summary.get("occurrences", [])
    for ev in events:
        if ev.get("type") == "result":
            summary = ev.get("summary") or {}
            tps = summary.get("third_pass_summary") or {}
            return tps.get("occurrences", [])
    return []


def parse_json_from_content(content: str) -> set[str]:
    try:
        payload = json.loads(content)
        return {str(o.get("canonical_form", "")).lower() for o in payload.get("occurrences", [])}
    except Exception:
        pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            payload = json.loads(m.group())
            return {str(o.get("canonical_form", "")).lower() for o in payload.get("occurrences", [])}
        except Exception:
            pass
    return set()


def test_llm_endpoint(llm_url: str, model: str) -> bool:
    print("\n" + "=" * 60)
    print("ТЕСТ 1: скорость LLM endpoint (streaming, think_mode=off)")
    print("=" * 60)
    ok = True
    for sentence, expected_forms in TEST_SENTENCES:
        prompt = build_direct_prompt(sentence)
        messages = [
            {"role": "system", "content": DIRECT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        print(f"\nТекст: {sentence[:80]}...")
        try:
            content, reasoning, elapsed, chunks = llm_stream_chat(
                llm_url, messages, model, think_mode=False
            )
        except Exception as e:
            print(f"  ОШИБКА: {e}")
            ok = False
            continue

        tok_per_sec = chunks / elapsed if elapsed > 0 else 0
        print(f"  Время:      {elapsed:.2f} с")
        print(f"  Всего чанков: {chunks}  ({tok_per_sec:.1f} tok/s)")
        if reasoning:
            print(f"  ⚠ Reasoning: {reasoning[:80]}...")
        print(f"  Контент:    {content[:300] or '(пусто)'}")

        found = parse_json_from_content(content)
        print(f"  Найдено:    {found}")
        hit = expected_forms & found
        miss = expected_forms - found
        if hit:
            print(f"  ✓ Совпадения: {hit}")
        if miss:
            print(f"  △ Пропущено:  {miss}  (допустимо — модель может использовать другой канон. вид)")
        if not found:
            print("  ОШИБКА: пустой результат")
            ok = False
    return ok


def test_gateway_integration(gateway_url: str) -> bool:
    print("\n" + "=" * 60)
    print("ТЕСТ 2: интеграция через gateway (/api/parse + SSE)")
    print("=" * 60)
    ok = True
    sentence, expected_forms = TEST_SENTENCES[0]
    print(f"Текст: {sentence[:80]}...")
    t0 = time.perf_counter()
    try:
        events = consume_sse_job(gateway_url, sentence)
    except Exception as e:
        print(f"  ОШИБКА: {e}")
        return False
    elapsed = time.perf_counter() - t0

    print(f"  Полное время: {elapsed:.2f} с")
    print(f"  Событий SSE: {len(events)}")

    stages = [e.get("stage") for e in events if e.get("type") == "stage_progress"]
    print(f"  Стадии:      {stages}")

    if "llm" not in stages:
        print("  ОШИБКА: llm stage_progress отсутствует — LLM не вызывалась!")
        ok = False

    llm_stage = next(
        (e for e in events if e.get("type") == "stage_progress" and e.get("stage") == "llm"),
        None,
    )
    if llm_stage:
        status = llm_stage.get("status")
        print(f"  LLM статус:  {status}")
        if status != "done":
            print(f"  LLM ошибка:  {llm_stage.get('message', '')}")
            ok = False

    llm_occ = extract_llm_occurrences(events)
    found = {str(o.get("canonical_form", "")).lower() for o in llm_occ}
    print(f"  LLM нашла:   {found}")

    hit = expected_forms & found
    miss = expected_forms - found
    if hit:
        print(f"  ✓ Совпадения: {hit}")
    if miss:
        print(f"  △ Пропущено:  {miss}")
    if not llm_occ:
        print("  ОШИБКА: LLM вернула пустые occurrences")
        ok = False
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-only", action="store_true", help="Только тест LLM endpoint, без gateway")
    parser.add_argument("--llm-url", default="http://127.0.0.1:8000")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    llm_url     = args.llm_url.rstrip("/")
    gateway_url = args.gateway_url.rstrip("/")

    print(f"Проверка LLM endpoint: {llm_url}/v1/models ...")
    try:
        models_resp = http_get(f"{llm_url}/v1/models", timeout=5.0)
        models = [m["id"] for m in models_resp.get("data", [])]
        model = models[0] if models else "Qwen3.5-9B-GGUF"
        print(f"Модель: {model}")
    except Exception as e:
        print(f"LLM endpoint недоступен ({e}). Запустите стек: ./start.sh")
        sys.exit(1)

    results = [test_llm_endpoint(llm_url, model)]

    if not args.llm_only:
        try:
            http_get(f"{gateway_url}/api/health", timeout=3.0)
            results.append(test_gateway_integration(gateway_url))
        except Exception:
            # gateway не имеет /api/health — пробуем /
            try:
                http_get(f"{gateway_url}/", timeout=3.0)
                results.append(test_gateway_integration(gateway_url))
            except Exception as e2:
                print(f"\nGateway недоступен ({gateway_url}: {e2}) — пропускаем тест 2.")

    print("\n" + "=" * 60)
    if all(results):
        print("ВСЕ ТЕСТЫ ПРОШЛИ")
    else:
        print("ЕСТЬ ОШИБКИ")
        sys.exit(1)


if __name__ == "__main__":
    main()
