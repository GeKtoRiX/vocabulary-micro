from __future__ import annotations

from typing import Any, List

from core.domain import TokenRecord
from infrastructure.config import PipelineSettings

from .text_utils import NON_LATIN_SCRIPT_PATTERN, TOKEN_PATTERN

try:
    import spacy

    # Активировать GPU (ROCm/CUDA) для spaCy трансформерных моделей.
    # prefer_gpu() возвращает True если GPU найден, иначе молча остаётся на CPU.
    spacy.prefer_gpu()
    SPACY_IMPORT_ERROR = None
except Exception as exc:
    spacy = None
    SPACY_IMPORT_ERROR = str(exc)


class TokenizerStage:
    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._spacy_nlp = None
        self._last_doc: Any | None = None
        self._last_backend = "unknown"
        self._spacy_pipeline_kind = "uninitialized"

    @property
    def spacy_available(self) -> bool:
        return spacy is not None

    @property
    def spacy_import_error(self) -> str | None:
        return SPACY_IMPORT_ERROR

    @property
    def last_backend(self) -> str:
        return str(self._last_backend or "unknown")

    def is_english(self, text: str) -> bool:
        return NON_LATIN_SCRIPT_PATTERN.search(text) is None

    def _get_spacy_nlp(self):
        if self._spacy_nlp is False:
            return None
        if self._spacy_nlp is not None:
            return self._spacy_nlp
        if spacy is None:
            self._spacy_nlp = False
            self._spacy_pipeline_kind = "spacy_unavailable"
            return None

        try:
            self._spacy_nlp = spacy.load(
                self._settings.spacy_trf_model_name,
                disable=self._spacy_disable_components(),
            )
            self._spacy_pipeline_kind = "spacy_model"
            return self._spacy_nlp
        except Exception:
            pass

        try:
            nlp = spacy.blank("en")
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")
            if "lemmatizer" not in nlp.pipe_names:
                nlp.add_pipe("lemmatizer", config={"mode": "rule"})
            nlp.initialize()
            self._spacy_nlp = nlp
            self._spacy_pipeline_kind = "spacy_blank"
            return self._spacy_nlp
        except Exception:
            self._spacy_nlp = False
            self._spacy_pipeline_kind = "spacy_init_failed"
            return None

    def _spacy_disable_components(self) -> list[str]:
        disabled = ["ner", "textcat"]
        # Keep parser when second pass is enabled so we can reuse one parsed Doc.
        if not self._settings.enable_second_pass_wsd:
            disabled.append("parser")
        return disabled

    def tokenize_with_doc(self, text: str) -> tuple[List[TokenRecord], bool, Any | None]:
        backend = "regex"
        tokens, doc = self._tokenize_with_spacy_doc(text)
        if tokens:
            if self._spacy_pipeline_kind in {"spacy_model", "spacy_blank"}:
                backend = self._spacy_pipeline_kind
            else:
                backend = "spacy"
        else:
            tokens = self._tokenize_with_regex(text)
            doc = None

        truncated = False
        if len(tokens) > self._settings.max_input_tokens:
            tokens = tokens[: self._settings.max_input_tokens]
            truncated = True
        self._last_doc = doc
        self._last_backend = backend
        return tokens, truncated, doc

    def tokenize(self, text: str) -> tuple[List[TokenRecord], bool]:
        tokens, truncated, _ = self.tokenize_with_doc(text)
        return tokens, truncated

    def _tokenize_with_spacy(self, text: str) -> List[TokenRecord]:
        tokens, _ = self._tokenize_with_spacy_doc(text)
        return tokens

    def _tokenize_with_spacy_doc(self, text: str) -> tuple[List[TokenRecord], Any | None]:
        nlp = self._get_spacy_nlp()
        if nlp is None:
            return [], None

        doc = nlp(text)
        tokens: List[TokenRecord] = []
        for token in doc:
            if token.is_space or token.is_punct or token.like_num:
                continue
            if not TOKEN_PATTERN.fullmatch(token.text):
                continue
            normalized = token.text.lower()
            lemma = (token.lemma_ or normalized).lower()
            if lemma == "-pron-" or not lemma.strip():
                lemma = normalized
            tokens.append(
                TokenRecord(
                    token=token.text,
                    normalized=normalized,
                    lemma=lemma,
                    pos=token.pos_ or "",
                    start=token.idx,
                    end=token.idx + len(token.text),
                )
            )
        return tokens, doc

    def _tokenize_with_regex(self, text: str) -> List[TokenRecord]:
        tokens: List[TokenRecord] = []
        for match in TOKEN_PATTERN.finditer(text):
            token = match.group(0)
            normalized = token.lower()
            tokens.append(
                TokenRecord(
                    token=token,
                    normalized=normalized,
                    lemma=normalized,
                    pos="",
                    start=match.start(),
                    end=match.end(),
                )
            )
        return tokens

    def pop_last_doc(self) -> Any | None:
        doc = self._last_doc
        self._last_doc = None
        return doc

    def pop_last_backend(self) -> str:
        backend = str(self._last_backend or "unknown")
        self._last_backend = "unknown"
        return backend

