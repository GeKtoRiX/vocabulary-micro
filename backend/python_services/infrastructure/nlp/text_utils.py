from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")
WEIRD_UNICODE_PATTERN = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# Broader non-Latin script detector: covers Cyrillic, Hebrew, Arabic, Devanagari,
# Japanese kana, CJK (Chinese/Japanese/Korean), and Hangul (Korean).
# Used by is_english() / _is_english_text() to reject definitively non-English input.
NON_LATIN_SCRIPT_PATTERN = re.compile(
    r"["
    r"\u0400-\u04FF"   # Cyrillic
    r"\u0590-\u05FF"   # Hebrew
    r"\u0600-\u06FF"   # Arabic
    r"\u0900-\u097F"   # Devanagari
    r"\u3040-\u30FF"   # Hiragana + Katakana
    r"\u3400-\u4DBF"   # CJK Extension A
    r"\u4E00-\u9FFF"   # CJK Unified Ideographs
    r"\uAC00-\uD7AF"   # Hangul Syllables
    r"\uF900-\uFAFF"   # CJK Compatibility Ideographs
    r"]"
)

def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def looks_like_weird_unicode(value: str) -> bool:
    return WEIRD_UNICODE_PATTERN.search(value) is not None
