from __future__ import annotations

from backend.python_services.core.domain.services import MweDetector, MweExpressionContext, MweTokenContext


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
        sentence_text="Fill in this form",
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


def test_detector_marks_spacy_trf_semantic_for_ambiguous_adp_particle() -> None:
    detector = MweDetector(
        second_pass_max_gap_tokens=4,
        wordnet_semantic_threshold=0.52,
        trf_semantic_threshold=0.58,
    )
    tokens = [
        _token(
            index=0,
            doc_index=0,
            text="Fill",
            lemma="fill",
            pos="VERB",
            dep="ROOT",
            start=0,
            end=4,
            children_indices=(1,),
        ),
        _token(
            index=1,
            doc_index=1,
            text="in",
            lemma="in",
            pos="ADP",
            dep="prep",
            start=5,
            end=7,
        ),
    ]
    expression = _fill_in_expression()
    candidates = detector.detect(
        text="Fill in",
        tokens=tokens,
        expressions={1: expression},
        contiguous_index={},
        separable_index={("fill", "in"): (1,)},
        wordnet_semantic_scorer=lambda *_: 0.0,
        trf_semantic_scorer=lambda *_: 0.91,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.canonical_form == "fill in"
    assert candidate.detection_source == "spacy_trf_semantic"
    assert candidate.semantic_boosted is True
    assert candidate.semantic_score >= 0.9


def test_detector_keeps_second_pass_spacy_for_prt_relation() -> None:
    detector = MweDetector(second_pass_max_gap_tokens=4)
    tokens = [
        _token(
            index=0,
            doc_index=0,
            text="Fill",
            lemma="fill",
            pos="VERB",
            dep="ROOT",
            start=0,
            end=4,
            children_indices=(1,),
        ),
        _token(
            index=1,
            doc_index=1,
            text="in",
            lemma="in",
            pos="ADP",
            dep="prt",
            start=5,
            end=7,
        ),
    ]
    expression = _fill_in_expression()
    candidates = detector.detect(
        text="Fill in",
        tokens=tokens,
        expressions={1: expression},
        contiguous_index={},
        separable_index={("fill", "in"): (1,)},
        wordnet_semantic_scorer=lambda *_: 0.0,
        trf_semantic_scorer=lambda *_: 0.0,
    )

    assert len(candidates) == 1
    assert candidates[0].detection_source == "second_pass_spacy"
    assert candidates[0].semantic_boosted is False


def test_detector_marks_second_pass_spacy_semantic_for_ambiguous_adp_with_wordnet_score() -> None:
    detector = MweDetector(
        second_pass_max_gap_tokens=4,
        wordnet_semantic_threshold=0.52,
        trf_semantic_threshold=0.58,
    )
    tokens = [
        _token(
            index=0,
            doc_index=0,
            text="Fill",
            lemma="fill",
            pos="VERB",
            dep="ROOT",
            start=0,
            end=4,
            children_indices=(1,),
        ),
        _token(
            index=1,
            doc_index=1,
            text="in",
            lemma="in",
            pos="ADP",
            dep="prep",
            start=5,
            end=7,
        ),
    ]
    expression = _fill_in_expression()
    candidates = detector.detect(
        text="Fill in",
        tokens=tokens,
        expressions={1: expression},
        contiguous_index={},
        separable_index={("fill", "in"): (1,)},
        wordnet_semantic_scorer=lambda *_: 0.86,
        trf_semantic_scorer=lambda *_: 0.12,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.detection_source == "second_pass_spacy_semantic"
    assert candidate.semantic_boosted is True
    assert candidate.semantic_score >= 0.86
