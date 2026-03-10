from __future__ import annotations

from dataclasses import dataclass

from infrastructure.sqlite.assignment_sentence_extractor import AssignmentSentenceExtractor


@dataclass
class _Sent:
    text: str


@dataclass
class _Doc:
    sents: list[_Sent]


class _TokenizerOk:
    def __init__(self, doc: _Doc | None) -> None:
        self._doc = doc

    def tokenize_with_doc(self, text: str):
        _ = text
        return [], False, self._doc


class _TokenizerFail:
    def tokenize_with_doc(self, text: str):
        _ = text
        raise RuntimeError("tokenizer down")


class _TokenizerNoSents:
    def tokenize_with_doc(self, text: str):
        _ = text
        return [], False, object()


def test_extract_sentence_returns_empty_for_blank_inputs() -> None:
    extractor = AssignmentSentenceExtractor()
    assert extractor.extract_sentence(text="", term="run") == ""
    assert extractor.extract_sentence(text="Some text", term="") == ""


def test_extract_sentence_prefers_spacy_sentence_when_available() -> None:
    extractor = AssignmentSentenceExtractor()
    extractor._tokenizer = _TokenizerOk(
        _Doc(
            sents=[
                _Sent("First sentence."),
                _Sent("We will run into issues tomorrow."),
            ]
        )
    )

    sentence = extractor.extract_sentence(
        text="First sentence. We will run into issues tomorrow. Last one.",
        term="run into",
    )
    assert sentence == "We will run into issues tomorrow."


def test_extract_sentence_falls_back_to_regex_when_spacy_fails() -> None:
    extractor = AssignmentSentenceExtractor()
    extractor._tokenizer = _TokenizerFail()

    sentence = extractor.extract_sentence(
        text="First part. Another sentence has RUN fast now! End.",
        term="run fast",
    )
    assert sentence == "Another sentence has RUN fast now!"


def test_extract_sentence_falls_back_to_regex_when_spacy_has_no_match() -> None:
    extractor = AssignmentSentenceExtractor()
    extractor._tokenizer = _TokenizerOk(_Doc(sents=[_Sent("No target here.")]))

    sentence = extractor.extract_sentence(
        text="No target here. Regex should find run quickly now.",
        term="run quickly",
    )
    assert sentence == "Regex should find run quickly now."


def test_extract_sentence_falls_back_to_regex_when_spacy_returns_no_doc() -> None:
    extractor = AssignmentSentenceExtractor()
    extractor._tokenizer = _TokenizerOk(None)

    sentence = extractor.extract_sentence(
        text="First part. Run quickly here.",
        term="run quickly",
    )
    assert sentence == "Run quickly here."


def test_extract_sentence_falls_back_to_regex_when_doc_has_no_sents() -> None:
    extractor = AssignmentSentenceExtractor()
    extractor._tokenizer = _TokenizerNoSents()

    sentence = extractor.extract_sentence(
        text="Nothing. We run slowly now.",
        term="run slowly",
    )
    assert sentence == "We run slowly now."


def test_extract_with_spacy_skips_empty_sentences() -> None:
    extractor = AssignmentSentenceExtractor()
    extractor._tokenizer = _TokenizerOk(
        _Doc(
            sents=[
                _Sent("   "),
                _Sent("We run at dawn."),
            ]
        )
    )
    assert extractor._extract_with_spacy("ignored", "run at") == "We run at dawn."


def test_extract_with_regex_returns_empty_when_nothing_matches() -> None:
    extractor = AssignmentSentenceExtractor()
    assert extractor._extract_with_regex("One. Two.", "missing term") == ""
    assert extractor._extract_with_regex("One sentence.   ", "missing term") == ""


def test_sentence_contains_term_uses_contiguous_token_windows() -> None:
    extractor = AssignmentSentenceExtractor()

    assert extractor._sentence_contains_term(sentence="We RUN into problems", term="run into") is True
    assert extractor._sentence_contains_term(sentence="We run directly into", term="run into") is False
    assert extractor._sentence_contains_term(sentence="Punctuation: run, into!", term="run into") is True
    assert extractor._sentence_contains_term(sentence="!!!", term="run") is False
