from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class MweTokenContext:
    index: int
    doc_index: int
    text: str
    lower: str
    lemma: str
    pos: str
    dep: str
    start: int
    end: int
    sentence_text: str
    children_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MweExpressionContext:
    expression_id: int
    canonical_form: str
    expression_type: str
    is_separable: bool
    max_gap_tokens: int
    base_lemma: str
    particle: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MweDetectionCandidate:
    expression_id: int
    canonical_form: str
    expression_type: str
    is_separable: bool
    span_start: int
    span_end: int
    token_start_index: int
    token_end_index: int
    surface: str
    sentence_text: str
    detection_source: str = "second_pass_spacy"
    semantic_score: float = 0.0
    semantic_boosted: bool = False


WordnetSemanticScorer = Callable[[MweTokenContext, MweTokenContext, MweExpressionContext], float]
TrfSemanticScorer = Callable[[MweTokenContext, MweTokenContext, MweExpressionContext], float]


class MweDetector:
    """Pure domain detector that relies on injected semantic scorers."""

    def __init__(
        self,
        *,
        second_pass_max_gap_tokens: int = 4,
        wordnet_semantic_threshold: float = 0.52,
        trf_semantic_threshold: float = 0.58,
    ) -> None:
        self._second_pass_max_gap_tokens = max(1, int(second_pass_max_gap_tokens))
        self._wordnet_semantic_threshold = max(0.0, float(wordnet_semantic_threshold))
        self._trf_semantic_threshold = max(0.0, float(trf_semantic_threshold))

    def detect(
        self,
        *,
        text: str,
        tokens: list[MweTokenContext],
        expressions: Mapping[int, MweExpressionContext],
        contiguous_index: Mapping[tuple[str, ...], tuple[int, ...]],
        separable_index: Mapping[tuple[str, str], tuple[int, ...]],
        wordnet_semantic_scorer: WordnetSemanticScorer | None = None,
        trf_semantic_scorer: TrfSemanticScorer | None = None,
    ) -> list[MweDetectionCandidate]:
        if not tokens:
            return []
        candidates: list[MweDetectionCandidate] = []
        candidates.extend(
            self._detect_contiguous(
                text=text,
                tokens=tokens,
                expressions=expressions,
                contiguous_index=contiguous_index,
            )
        )
        candidates.extend(
            self._detect_separable(
                text=text,
                tokens=tokens,
                expressions=expressions,
                separable_index=separable_index,
                wordnet_semantic_scorer=wordnet_semantic_scorer,
                trf_semantic_scorer=trf_semantic_scorer,
            )
        )
        return self._dedupe_overlaps(candidates)

    def _detect_contiguous(
        self,
        *,
        text: str,
        tokens: list[MweTokenContext],
        expressions: Mapping[int, MweExpressionContext],
        contiguous_index: Mapping[tuple[str, ...], tuple[int, ...]],
    ) -> list[MweDetectionCandidate]:
        lengths = sorted({len(key) for key in contiguous_index.keys()}, reverse=True)
        if not lengths:
            return []
        normalized = [token.lower for token in tokens]
        lemmas = [token.lemma or token.lower for token in tokens]
        total = len(tokens)
        found: list[MweDetectionCandidate] = []
        used: set[tuple[int, int, int]] = set()
        for start in range(total):
            for length in lengths:
                end = start + length
                if end > total:
                    continue
                key = tuple(normalized[start:end])
                lemma_key = tuple(lemmas[start:end])
                expression_ids: set[int] = set(contiguous_index.get(key, ()))
                if lemma_key != key:
                    expression_ids.update(contiguous_index.get(lemma_key, ()))
                if not expression_ids:
                    continue
                for expression_id in sorted(expression_ids):
                    expression = expressions.get(expression_id)
                    if expression is None:
                        continue
                    candidate = self._build_candidate(
                        text=text,
                        token_start=tokens[start],
                        token_end=tokens[end - 1],
                        token_start_index=start,
                        token_end_index=end - 1,
                        expression=expression,
                        detection_source="second_pass_spacy",
                        semantic_score=0.0,
                        semantic_boosted=False,
                    )
                    marker = (candidate.expression_id, candidate.token_start_index, candidate.token_end_index)
                    if marker in used:
                        continue
                    used.add(marker)
                    found.append(candidate)
        return found

    def _detect_separable(
        self,
        *,
        text: str,
        tokens: list[MweTokenContext],
        expressions: Mapping[int, MweExpressionContext],
        separable_index: Mapping[tuple[str, str], tuple[int, ...]],
        wordnet_semantic_scorer: WordnetSemanticScorer | None,
        trf_semantic_scorer: TrfSemanticScorer | None,
    ) -> list[MweDetectionCandidate]:
        by_verb: dict[str, list[tuple[str, tuple[int, ...]]]] = {}
        for (verb, particle), expression_ids in separable_index.items():
            by_verb.setdefault(str(verb), []).append((str(particle), tuple(expression_ids)))

        found: list[MweDetectionCandidate] = []
        used: set[tuple[int, int, int]] = set()
        for index, token in enumerate(tokens):
            lemma = (token.lemma or token.lower).strip().lower()
            if not lemma:
                continue
            options = by_verb.get(lemma, ())
            if not options:
                continue
            for particle, expression_ids in options:
                particle_index = self._find_particle_index(
                    token_index=index,
                    tokens=tokens,
                    particle=particle,
                    max_gap=self._second_pass_max_gap_tokens,
                )
                if particle_index is None or particle_index <= index:
                    continue
                particle_token = tokens[particle_index]
                for expression_id in expression_ids:
                    expression = expressions.get(expression_id)
                    if expression is None or not expression.is_separable:
                        continue
                    gap_limit = expression.max_gap_tokens or self._second_pass_max_gap_tokens
                    if (particle_index - index - 1) > int(gap_limit):
                        continue

                    dep = str(particle_token.dep or "").strip().lower()
                    pos = str(particle_token.pos or "").strip().upper()
                    is_particle_relation = dep in {"prt", "compound:prt"} or pos == "PART"
                    is_ambiguous_relation = dep in {"prep", "advmod"} or pos in {"ADP", "ADV"}

                    wordnet_score = 0.0
                    if wordnet_semantic_scorer is not None:
                        try:
                            wordnet_score = float(
                                wordnet_semantic_scorer(token, particle_token, expression)
                            )
                        except Exception:
                            wordnet_score = 0.0

                    trf_score = 0.0
                    if trf_semantic_scorer is not None:
                        try:
                            trf_score = float(
                                trf_semantic_scorer(token, particle_token, expression)
                            )
                        except Exception:
                            trf_score = 0.0

                    semantic_score = max(wordnet_score, trf_score)
                    semantic_boosted = False
                    detection_source = "second_pass_spacy"
                    if is_ambiguous_relation and trf_score >= self._trf_semantic_threshold:
                        detection_source = "spacy_trf_semantic"
                        semantic_boosted = True
                    elif is_ambiguous_relation and wordnet_score >= self._wordnet_semantic_threshold:
                        detection_source = "second_pass_spacy_semantic"
                        semantic_boosted = True
                    elif not is_particle_relation and not is_ambiguous_relation and semantic_score <= 0.0:
                        # Keep conservative behavior for non-particle links without semantic evidence.
                        continue

                    candidate = self._build_candidate(
                        text=text,
                        token_start=token,
                        token_end=particle_token,
                        token_start_index=index,
                        token_end_index=particle_index,
                        expression=expression,
                        detection_source=detection_source,
                        semantic_score=semantic_score,
                        semantic_boosted=semantic_boosted,
                    )
                    marker = (candidate.expression_id, candidate.token_start_index, candidate.token_end_index)
                    if marker in used:
                        continue
                    used.add(marker)
                    found.append(candidate)
        return found

    def _find_particle_index(
        self,
        *,
        token_index: int,
        tokens: list[MweTokenContext],
        particle: str,
        max_gap: int,
    ) -> int | None:
        max_gap = max(1, int(max_gap))
        token = tokens[token_index]
        for child_index in token.children_indices:
            if child_index <= token_index or child_index >= len(tokens):
                continue
            child = tokens[child_index]
            if child.lower != particle:
                continue
            if (child_index - token_index - 1) <= max_gap:
                return child_index

        max_end = min(len(tokens), token_index + max_gap + 2)
        for probe_index in range(token_index + 1, max_end):
            probe = tokens[probe_index]
            if probe.lower != particle:
                continue
            dep = str(probe.dep or "").strip().lower()
            pos = str(probe.pos or "").strip().upper()
            if dep in {"prt", "compound:prt", "prep", "advmod"} or pos in {"PART", "ADP", "ADV"}:
                return probe_index
        return None

    def _build_candidate(
        self,
        *,
        text: str,
        token_start: MweTokenContext,
        token_end: MweTokenContext,
        token_start_index: int,
        token_end_index: int,
        expression: MweExpressionContext,
        detection_source: str,
        semantic_score: float,
        semantic_boosted: bool,
    ) -> MweDetectionCandidate:
        span_start = int(token_start.start)
        span_end = int(token_end.end)
        if span_end < span_start:
            span_end = span_start
        surface = text[span_start:span_end]
        sentence_text = token_start.sentence_text or text.strip()
        return MweDetectionCandidate(
            expression_id=expression.expression_id,
            canonical_form=expression.canonical_form,
            expression_type=expression.expression_type,
            is_separable=expression.is_separable,
            span_start=span_start,
            span_end=span_end,
            token_start_index=token_start_index,
            token_end_index=token_end_index,
            surface=surface,
            sentence_text=sentence_text,
            detection_source=detection_source,
            semantic_score=max(0.0, float(semantic_score)),
            semantic_boosted=bool(semantic_boosted),
        )

    def _dedupe_overlaps(
        self,
        candidates: Iterable[MweDetectionCandidate],
    ) -> list[MweDetectionCandidate]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.token_end_index - item.token_start_index,
                1 if item.semantic_boosted else 0,
                float(item.semantic_score),
                1 if item.expression_type == "idiom" else 0,
                1 if item.is_separable else 0,
            ),
            reverse=True,
        )
        selected: list[MweDetectionCandidate] = []
        occupied: list[tuple[int, int]] = []
        for item in ranked:
            interval = (item.token_start_index, item.token_end_index)
            intersects = any(
                not (interval[1] < existing[0] or interval[0] > existing[1])
                for existing in occupied
            )
            if intersects:
                continue
            selected.append(item)
            occupied.append(interval)
        selected.sort(key=lambda item: (item.span_start, item.span_end))
        return selected
