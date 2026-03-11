from __future__ import annotations

import pytest

from backend.python_services.core.domain.services.text_processor import TextProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(
    normalized: str,
    pos: str = "",
    dep: str = "",
    lemma: str | None = None,
) -> dict:
    return {
        "token": normalized,
        "normalized": normalized,
        "lemma": lemma if lemma is not None else normalized,
        "pos": pos,
        "dep": dep,
    }


@pytest.fixture()
def tp() -> TextProcessor:
    return TextProcessor()


# ---------------------------------------------------------------------------
# Fix 1 — normalize_lexeme: words ending in -ss must not be stripped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    # Double-s words that must NOT be stripped
    ("news", "news"),
    ("class", "class"),
    ("grass", "grass"),
    ("mass", "mass"),
    ("always", "always"),
    ("address", "address"),
    ("glass", "glass"),
    ("pass", "pass"),
    ("cross", "cross"),
    ("loss", "loss"),
    ("boss", "boss"),
    # Legitimate plural stripping must remain correct
    ("runs", "run"),
    ("books", "book"),
    ("dogs", "dog"),
    ("cats", "cat"),
    # Existing exclusions unchanged
    ("this", "this"),
    ("these", "these"),
    ("those", "those"),
])
def test_normalize_lexeme_ss_words_not_stripped(tp, raw, expected):
    assert tp.normalize_lexeme(raw) == expected


# ---------------------------------------------------------------------------
# Fix 2 — normalize_verb_head: new irregular verb forms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    # New entries
    ("got", "get"),
    ("gotten", "get"),
    ("fell", "fall"),
    ("fallen", "fall"),
    ("broke", "break"),
    ("broken", "break"),
    ("woke", "wake"),
    ("woken", "wake"),
    ("won", "win"),
    ("lost", "lose"),
    ("built", "build"),
    ("dealt", "deal"),
    ("wore", "wear"),
    ("worn", "wear"),
    ("threw", "throw"),
    ("thrown", "throw"),
    ("grew", "grow"),
    ("grown", "grow"),
    ("drew", "draw"),
    ("drawn", "draw"),
    ("blew", "blow"),
    ("blown", "blow"),
    ("drove", "drive"),
    ("driven", "drive"),
    # Pre-existing entries must still work
    ("ran", "run"),
    ("went", "go"),
    ("gone", "go"),
    ("took", "take"),
    ("wrote", "write"),
    ("written", "write"),
    ("called", "call"),
    # Base forms unchanged
    ("run", "run"),
    ("go", "go"),
])
def test_normalize_verb_head_new_irregulars(tp, raw, expected):
    assert tp.normalize_verb_head(raw) == expected


# ---------------------------------------------------------------------------
# Fix 3 — canonicalize_expression: idiom guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,etype,expected", [
    # Idioms with non-verb-initial words must NOT be normalized
    ("blessing in disguise", "idiom", "blessing in disguise"),
    ("a blessing in disguise", "idiom", "a blessing in disguise"),
    ("the whole nine yards", "idiom", "the whole nine yards"),
    ("in the heat of the moment", "idiom", "in the heat of the moment"),
    ("raining cats and dogs", "idiom", "raining cats and dogs"),
    # Idioms starting with irregular verb forms MUST be normalized
    ("called it a day", "idiom", "call it a day"),
    ("went out of his way", "idiom", "go out of his way"),
    ("ran rings around", "idiom", "run rings around"),
    ("tried and tested", "idiom", "try and tested"),  # -ied rule
    # Idioms already in base form — unchanged
    ("call it a day", "idiom", "call it a day"),
    ("go the extra mile", "idiom", "go the extra mile"),
    # Phrasal verbs always normalize unconditionally
    ("ran into", "phrasal_verb", "run into"),
    ("went out", "phrasal_verb", "go out"),
    ("looked up", "phrasal_verb", "look up"),
    ("got up", "phrasal_verb", "get up"),
    ("broke down", "phrasal_verb", "break down"),
    # No type: fallback heuristic (ends with particle) unchanged
    ("running out", "", "run out"),
    ("look up", "", "look up"),
])
def test_canonicalize_expression_idiom_normalization(tp, raw, etype, expected):
    assert tp.canonicalize_expression(raw, expression_type=etype) == expected


# ---------------------------------------------------------------------------
# Fix 4 — extract_phrasal_verbs: three-word phrasal verbs
# ---------------------------------------------------------------------------

def test_extract_phrasal_verbs_detects_three_word_look_up_to(tp):
    """look up to: both 'up' and 'to' (with dep=prt) are in PHRASAL_PARTICLES."""
    tokens = [
        _make_token("look", pos="VERB"),
        _make_token("up", pos="PART"),
        _make_token("to", pos="PART", dep="prt"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "look up to" in result


def test_extract_phrasal_verbs_detects_three_word_come_up_with(tp):
    tokens = [
        _make_token("come", pos="VERB", lemma="come"),
        _make_token("up", pos="PART"),
        _make_token("with", pos="PART", dep="prt"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "come up with" in result


def test_extract_phrasal_verbs_detects_three_word_get_away_with(tp):
    tokens = [
        _make_token("get", pos="VERB"),
        _make_token("away", pos="PART"),
        _make_token("with", pos="PART", dep="prt"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "get away with" in result


def test_extract_phrasal_verbs_falls_back_to_two_word_without_second_particle(tp):
    tokens = [
        _make_token("look", pos="VERB"),
        _make_token("up", pos="PART"),
        _make_token("something", pos="NOUN"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "look up" in result
    assert not any(p.count(" ") >= 2 for p in result)


def test_extract_phrasal_verbs_two_word_no_regression(tp):
    tokens = [
        _make_token("get", pos="VERB"),
        _make_token("the", pos="DET"),
        _make_token("out", pos="PART"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "get out" in result


def test_extract_phrasal_verbs_irregular_verb_normalized(tp):
    tokens = [
        _make_token("got", pos="VERB", lemma="got"),
        _make_token("up", pos="PART"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "get up" in result


def test_extract_phrasal_verbs_broke_down(tp):
    tokens = [
        _make_token("broke", pos="VERB", lemma="broke"),
        _make_token("down", pos="PART"),
    ]
    result = tp.extract_phrasal_verbs(tokens)
    assert "break down" in result
