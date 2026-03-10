from __future__ import annotations

import re

from infrastructure.config import PipelineSettings

from .text_utils import TOKEN_PATTERN, normalize_whitespace
from .tokenizer import TokenizerStage


SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


class AssignmentSentenceExtractor:
    """Extract first sentence containing a term, preferring spaCy TRF boundaries."""

    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self._settings = settings or PipelineSettings.from_env()
        self._tokenizer = TokenizerStage(self._settings)

    def extract_sentence(self, *, text: str, term: str) -> str:
        clean_text = normalize_whitespace(str(text or ""))
        clean_term = normalize_whitespace(str(term or "")).casefold()
        if not clean_text or not clean_term:
            return ""

        sentence = self._extract_with_spacy(clean_text, clean_term)
        if sentence:
            return sentence
        return self._extract_with_regex(clean_text, clean_term)

    def _extract_with_spacy(self, text: str, term: str) -> str:
        try:
            _, _, doc = self._tokenizer.tokenize_with_doc(text)
        except Exception:
            return ""
        if doc is None:
            return ""
        sentence_iter = getattr(doc, "sents", None)
        if sentence_iter is None:
            return ""
        for sent in sentence_iter:
            sentence = normalize_whitespace(str(getattr(sent, "text", "") or ""))
            if not sentence:
                continue
            if self._sentence_contains_term(sentence=sentence, term=term):
                return sentence
        return ""

    def _extract_with_regex(self, text: str, term: str) -> str:
        for sentence in SENTENCE_SPLIT_PATTERN.split(text):
            clean = normalize_whitespace(sentence)
            if not clean:
                continue
            if self._sentence_contains_term(sentence=clean, term=term):
                return clean
        return ""

    def _sentence_contains_term(self, *, sentence: str, term: str) -> bool:
        sentence_tokens = [item.casefold() for item in TOKEN_PATTERN.findall(sentence)]
        term_tokens = [item.casefold() for item in TOKEN_PATTERN.findall(term)]
        if not sentence_tokens or not term_tokens:
            return False
        target_size = len(term_tokens)
        for index in range(0, len(sentence_tokens) - target_size + 1):
            if sentence_tokens[index : index + target_size] == term_tokens:
                return True
        return False

