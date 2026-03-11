from __future__ import annotations

from backend.python_services.infrastructure.config import PipelineSettings
from backend.python_services.infrastructure.nlp.lexicon_engine import LexiconEngine
from backend.python_services.core.domain import TokenRecord


class _StubLexiconEngine(LexiconEngine):
    def iter_entries(self):  # noqa: ANN201
        return []


def _build_token(
    *,
    token: str,
    pos: str,
    categories: list[str] | None = None,
    match_source: str = "none",
) -> TokenRecord:
    return TokenRecord(
        token=token,
        normalized=token.lower(),
        lemma=token.lower(),
        pos=pos,
        start=0,
        end=len(token),
        categories=list(categories or []),
        known=bool(categories),
        match_source=match_source,
        matched_form=token.lower() if categories else "",
        bert_score=None,
    )


def test_apply_pos_hints_keeps_single_existing_category_without_extra_hint() -> None:
    engine = _StubLexiconEngine(settings=PipelineSettings())
    token = _build_token(
        token="Hello",
        pos="INTJ",
        categories=["Auto Added"],
        match_source="exact",
    )

    engine._apply_pos_category_hints([token])

    assert token.categories == ["Auto Added"]


def test_apply_pos_hints_sets_hint_for_uncategorized_token() -> None:
    engine = _StubLexiconEngine(settings=PipelineSettings())
    token = _build_token(
        token="Hello",
        pos="INTJ",
    )

    engine._apply_pos_category_hints([token])

    assert token.categories == ["Interjection"]
    assert token.match_source == "spacy_pos_hint"
