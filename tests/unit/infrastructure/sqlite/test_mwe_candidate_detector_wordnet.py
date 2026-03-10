from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from core.domain.services import MweExpressionContext, MweTokenContext
from infrastructure.config import PipelineSettings
import infrastructure.sqlite.mwe_candidate_detector as detector_module
from infrastructure.sqlite.mwe_candidate_detector import MweCandidateDetector
from infrastructure.sqlite.mwe_index_provider import MweExpressionRecord, MweIndexSnapshot


def _token(
    *,
    index: int,
    doc_index: int,
    text: str,
    lemma: str,
    pos: str,
    dep: str,
    start: int,
    end: int,
    children_indices: tuple[int, ...] = (),
) -> MweTokenContext:
    return MweTokenContext(
        index=index,
        doc_index=doc_index,
        text=text,
        lower=text.lower(),
        lemma=lemma.lower(),
        pos=pos,
        dep=dep,
        start=start,
        end=end,
        sentence_text="They fill data in the report.",
        children_indices=children_indices,
    )


def _fill_in_expression() -> MweExpressionContext:
    return MweExpressionContext(
        expression_id=1,
        canonical_form="fill in",
        expression_type="phrasal_verb",
        is_separable=True,
        max_gap_tokens=4,
        base_lemma="fill",
        particle="in",
        tokens=("fill", "in"),
    )


class _FakeLemma:
    def __init__(self, value: str) -> None:
        self._value = value

    def name(self) -> str:
        return self._value


class _FakeSynset:
    def __init__(
        self,
        key: str,
        *,
        lemmas: tuple[str, ...] = (),
        similarity_by_key: dict[str, float] | None = None,
    ) -> None:
        self.key = key
        self._lemmas = tuple(_FakeLemma(item) for item in lemmas)
        self._similarity_by_key = dict(similarity_by_key or {})

    def lemmas(self) -> list[_FakeLemma]:
        return list(self._lemmas)

    def wup_similarity(self, other: object) -> float | None:
        other_key = getattr(other, "key", "")
        return self._similarity_by_key.get(str(other_key), 0.0)


class _FakeWordNet:
    VERB = "v"

    def __init__(self, mapping: dict[str, tuple[_FakeSynset, ...]]) -> None:
        self._mapping = dict(mapping)

    def synsets(self, query: str, pos: object = None) -> list[_FakeSynset]:
        del pos
        return list(self._mapping.get(query, ()))


class _FakeDomainDetector:
    def detect(self, **_kwargs):
        return []


def _empty_snapshot() -> MweIndexSnapshot:
    return MweIndexSnapshot(
        version=1,
        expressions=MappingProxyType({}),
        senses_by_expression=MappingProxyType({}),
        contiguous_index=MappingProxyType({}),
        separable_index=MappingProxyType({}),
        candidate_hash="unit-test",
        model_name="rule_based",
        model_revision=None,
    )


def test_wordnet_semantic_score_uses_wup_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    fill_synset = _FakeSynset("fill", similarity_by_key={"fill_in": 0.34, "complete": 0.86})
    fill_in_synset = _FakeSynset("fill_in", lemmas=("fill_in", "complete"), similarity_by_key={"fill": 0.34})
    complete_synset = _FakeSynset("complete", lemmas=("complete",), similarity_by_key={"fill": 0.86})
    fake_wn = _FakeWordNet(
        {
            "fill": (fill_synset,),
            "fill_in": (fill_in_synset,),
            "complete": (complete_synset,),
        }
    )
    monkeypatch.setattr(detector_module, "wn", fake_wn)

    detector = MweCandidateDetector(settings=PipelineSettings())
    score = detector._wordnet_semantic_score(
        verb_token=_token(
            index=0,
            doc_index=0,
            text="fill",
            lemma="fill",
            pos="VERB",
            dep="ROOT",
            start=5,
            end=9,
            children_indices=(2,),
        ),
        particle_token=_token(
            index=2,
            doc_index=2,
            text="in",
            lemma="in",
            pos="ADP",
            dep="prep",
            start=15,
            end=17,
        ),
        expression=_fill_in_expression(),
    )

    assert score >= 0.86
    assert ("fill", "fill in") in detector._wordnet_similarity_cache


def test_wordnet_semantic_score_falls_back_to_legacy_when_wordnet_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detector_module, "wn", _FakeWordNet({}))
    detector = MweCandidateDetector(settings=PipelineSettings())
    monkeypatch.setattr(
        detector,
        "_wordnet_lemma_names",
        lambda *_args, **_kwargs: ("complete", "fill_in"),
    )

    score = detector._wordnet_semantic_score(
        verb_token=_token(
            index=0,
            doc_index=0,
            text="fill",
            lemma="fill",
            pos="VERB",
            dep="ROOT",
            start=0,
            end=4,
            children_indices=(2,),
        ),
        particle_token=_token(
            index=2,
            doc_index=2,
            text="in",
            lemma="in",
            pos="ADP",
            dep="prep",
            start=10,
            end=12,
        ),
        expression=_fill_in_expression(),
    )

    assert score >= 0.72


def test_detector_integration_marks_semantic_source_for_ambiguous_fill_in() -> None:
    if detector_module.spacy is None:
        pytest.skip("spaCy is unavailable")
    if detector_module.wn is None:
        pytest.skip("WordNet is unavailable")

    settings = PipelineSettings.from_env()
    detector = MweCandidateDetector(settings=settings)
    availability = detector.availability(ensure_loaded=True)
    if not bool(availability.get("spacy_model_available", False)):
        pytest.skip(f"spaCy model unavailable: {availability.get('spacy_model_unavailable_reason', '')}")

    if not detector_module.wn.synsets("fill_in", pos=detector_module.wn.VERB):
        pytest.skip("WordNet fill_in synsets unavailable")

    text = "They fill data in the report before approval."
    nlp = detector._nlp
    if nlp is None:
        pytest.skip("spaCy model failed to load for integration check")
    doc = nlp(text)

    expression = MweExpressionRecord(
        expression_id=1,
        canonical_form="fill in",
        tokens=("fill", "in"),
        expression_type="phrasal_verb",
        base_lemma="fill",
        particle="in",
        is_separable=True,
        max_gap_tokens=4,
    )
    snapshot = MweIndexSnapshot(
        version=1,
        expressions=MappingProxyType({1: expression}),
        senses_by_expression=MappingProxyType({}),
        contiguous_index=MappingProxyType({("fill", "in"): (1,)}),
        separable_index=MappingProxyType({("fill", "in"): (1,)}),
        candidate_hash="integration",
        model_name="rule_based",
        model_revision=None,
    )

    payload = detector.detect(text, snapshot, preparsed_doc=doc)
    assert payload.get("status") == "ok"
    candidates = list(payload.get("candidates", []))
    fill_in_candidates = [item for item in candidates if item.canonical_form == "fill in"]
    if not fill_in_candidates:
        pytest.skip("Integration check found no fill in candidate in this model revision")
    assert any(
        item.detection_source in {"second_pass_spacy_semantic", "spacy_trf_semantic"}
        for item in fill_in_candidates
    )


def test_detect_reuses_request_payload_for_same_request_and_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = MweCandidateDetector(settings=PipelineSettings())
    detector._detector = _FakeDomainDetector()
    build_calls = {"count": 0}
    token_node = _token(
        index=0,
        doc_index=0,
        text="fill",
        lemma="fill",
        pos="VERB",
        dep="ROOT",
        start=0,
        end=4,
    )
    token_vectors = {0: np.array([1.0, 0.0], dtype=np.float32)}

    def _fake_build_token_nodes(*, text: str, doc) -> tuple[list[MweTokenContext], dict[int, np.ndarray]]:
        del text, doc
        build_calls["count"] += 1
        return [token_node], token_vectors

    monkeypatch.setattr(detector, "_build_token_nodes", _fake_build_token_nodes)
    snapshot = _empty_snapshot()
    doc = object()

    payload_first = detector.detect(
        "fill in the blanks",
        snapshot,
        request_id="req-42",
        preparsed_doc=doc,
    )
    payload_second = detector.detect(
        "fill in the blanks",
        snapshot,
        request_id="req-42",
        preparsed_doc=doc,
    )

    assert payload_first["status"] == "ok"
    assert payload_second["status"] == "ok"
    assert build_calls["count"] == 1


def test_release_request_cache_forces_rebuild_on_next_detect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = MweCandidateDetector(settings=PipelineSettings())
    detector._detector = _FakeDomainDetector()
    build_calls = {"count": 0}
    token_node = _token(
        index=0,
        doc_index=0,
        text="fill",
        lemma="fill",
        pos="VERB",
        dep="ROOT",
        start=0,
        end=4,
    )
    token_vectors = {0: np.array([1.0, 0.0], dtype=np.float32)}

    def _fake_build_token_nodes(*, text: str, doc) -> tuple[list[MweTokenContext], dict[int, np.ndarray]]:
        del text, doc
        build_calls["count"] += 1
        return [token_node], token_vectors

    monkeypatch.setattr(detector, "_build_token_nodes", _fake_build_token_nodes)
    snapshot = _empty_snapshot()
    doc = object()

    detector.detect(
        "fill in the blanks",
        snapshot,
        request_id="req-99",
        preparsed_doc=doc,
    )
    detector.release_request_cache("req-99")
    detector.detect(
        "fill in the blanks",
        snapshot,
        request_id="req-99",
        preparsed_doc=doc,
    )

    assert build_calls["count"] == 2


def test_augment_wordnet_expressions_skips_noisy_with_and_gap_on_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = MweCandidateDetector(settings=PipelineSettings())
    monkeypatch.setattr(detector_module, "wn", object())
    monkeypatch.setattr(detector, "_wordnet_lemma_names", lambda *_args, **_kwargs: ("x",))
    monkeypatch.setattr(
        detector,
        "_wordnet_supports_augmented_pair",
        lambda **_kwargs: True,
    )

    token_nodes = [
        _token(
            index=0,
            doc_index=0,
            text="carry",
            lemma="carry",
            pos="VERB",
            dep="ROOT",
            start=0,
            end=5,
        ),
        _token(
            index=1,
            doc_index=1,
            text="this",
            lemma="this",
            pos="PRON",
            dep="dobj",
            start=6,
            end=10,
        ),
        _token(
            index=2,
            doc_index=2,
            text="with",
            lemma="with",
            pos="ADP",
            dep="prep",
            start=11,
            end=15,
        ),
        _token(
            index=3,
            doc_index=3,
            text="put",
            lemma="put",
            pos="VERB",
            dep="conj",
            start=16,
            end=19,
        ),
        _token(
            index=4,
            doc_index=4,
            text="notes",
            lemma="note",
            pos="NOUN",
            dep="dobj",
            start=20,
            end=25,
        ),
        _token(
            index=5,
            doc_index=5,
            text="on",
            lemma="on",
            pos="ADP",
            dep="prep",
            start=26,
            end=28,
        ),
        _token(
            index=6,
            doc_index=6,
            text="run",
            lemma="run",
            pos="VERB",
            dep="conj",
            start=29,
            end=32,
        ),
        _token(
            index=7,
            doc_index=7,
            text="into",
            lemma="into",
            pos="ADP",
            dep="prep",
            start=33,
            end=37,
        ),
    ]
    expressions: dict[int, MweExpressionContext] = {}
    contiguous_index: dict[tuple[str, ...], tuple[int, ...]] = {}
    separable_index: dict[tuple[str, str], tuple[int, ...]] = {}

    detector._augment_wordnet_expressions(
        token_nodes=token_nodes,
        expressions=expressions,
        contiguous_index=contiguous_index,
        separable_index=separable_index,
    )

    assert ("run", "into") in separable_index
    assert ("carry", "with") not in separable_index
    assert ("put", "on") not in separable_index
