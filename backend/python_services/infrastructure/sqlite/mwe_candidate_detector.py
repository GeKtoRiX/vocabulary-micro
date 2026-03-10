from __future__ import annotations

from collections import OrderedDict
import importlib.util
from threading import RLock

import numpy as np

from core.domain.services import MweDetector, MweExpressionContext, MweTokenContext
from infrastructure.config import PipelineSettings
from infrastructure.sqlite.mwe_models import MweCandidate

from .mwe_index_provider import MweIndexSnapshot

try:
    import spacy
except Exception:
    spacy = None

try:
    from nltk.corpus import wordnet as wn
except Exception:
    wn = None

PHRASAL_PARTICLES = {
    "up",
    "down",
    "in",
    "out",
    "on",
    "off",
    "away",
    "back",
    "over",
    "through",
    "around",
    "about",
    "along",
    "into",
    "onto",
    "upon",
    "across",
    "by",
    "for",
    "from",
    "to",
    "with",
}
WEAK_PHRASAL_PARTICLES = {"with", "for", "from", "to", "by"}
PHRASAL_PARTICLE_POS = {"ADP", "PART", "ADV"}
PHRASAL_PARTICLE_DEP = {"prt", "compound:prt"}


class MweCandidateDetector:
    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._nlp = None
        self._unavailable_reason: str | None = None
        self._detector = MweDetector(
            second_pass_max_gap_tokens=settings.second_pass_max_gap_tokens,
            wordnet_semantic_threshold=0.52,
            trf_semantic_threshold=0.4,
        )
        self._reference_cache_lock = RLock()
        self._reference_vector_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._reference_cache_max_entries = 512
        self._wordnet_lemma_cache: OrderedDict[str, tuple[str, ...]] = OrderedDict()
        self._wordnet_cache_max_entries = 2048
        self._wordnet_synset_cache: OrderedDict[str, tuple[object, ...]] = OrderedDict()
        self._wordnet_synset_cache_max_entries = 2048
        self._wordnet_similarity_cache: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._wordnet_similarity_cache_max_entries = 4096
        self._request_payload_cache: OrderedDict[
            str,
            tuple[str, int, list[MweTokenContext], dict[int, np.ndarray]],
        ] = OrderedDict()
        self._request_payload_cache_max_entries = 64

    def availability(self, *, ensure_loaded: bool = True) -> dict[str, object]:
        model_name = self._settings.spacy_trf_model_name
        installed = bool(importlib.util.find_spec(model_name))
        if ensure_loaded:
            available = self._ensure_model()
        elif self._nlp is not None:
            available = True
        elif self._unavailable_reason is not None:
            available = False
        else:
            available = installed and spacy is not None
        return {
            "spacy_model": model_name,
            "spacy_model_installed": installed,
            "spacy_model_available": available,
            "spacy_model_unavailable_reason": self._unavailable_reason,
            "trf_semantic_enabled": True,
        }

    def detect(
        self,
        text: str,
        snapshot: MweIndexSnapshot,
        *,
        request_id: str | None = None,
        preparsed_doc=None,
    ) -> dict[str, object]:
        if preparsed_doc is not None:
            if self._nlp is None and self._unavailable_reason is None:
                self._ensure_model()
            try:
                return {
                    "status": "ok",
                    "reason": "",
                    "candidates": self._detect_from_doc(
                        text=text,
                        doc=preparsed_doc,
                        snapshot=snapshot,
                        request_id=request_id,
                    ),
                    "used_preparsed_doc": True,
                }
            except Exception:
                pass

        if not self._ensure_model():
            return {
                "status": "skipped",
                "reason": self._unavailable_reason or "spacy_model_unavailable",
                "candidates": [],
                "used_preparsed_doc": False,
            }
        nlp = self._nlp
        if nlp is None:
            return {
                "status": "skipped",
                "reason": "spacy_model_unavailable",
                "candidates": [],
                "used_preparsed_doc": False,
            }
        doc = nlp(text)
        return {
            "status": "ok",
            "reason": "",
            "candidates": self._detect_from_doc(
                text=text,
                doc=doc,
                snapshot=snapshot,
                request_id=request_id,
            ),
            "used_preparsed_doc": False,
        }

    def _detect_from_doc(
        self,
        *,
        text: str,
        doc,
        snapshot: MweIndexSnapshot,
        request_id: str | None,
    ) -> list[MweCandidate]:
        token_nodes, doc_token_vectors = self._resolve_request_payload(
            text=text,
            doc=doc,
            request_id=request_id,
        )
        if not token_nodes:
            return []
        expression_nodes = {
            expression_id: MweExpressionContext(
                expression_id=expression.expression_id,
                canonical_form=expression.canonical_form,
                expression_type=expression.expression_type,
                is_separable=expression.is_separable,
                max_gap_tokens=expression.max_gap_tokens,
                base_lemma=expression.base_lemma,
                particle=expression.particle,
                tokens=expression.tokens,
            )
            for expression_id, expression in snapshot.expressions.items()
        }
        contiguous_index = {
            tuple(key): tuple(value)
            for key, value in snapshot.contiguous_index.items()
        }
        separable_index = {
            tuple(key): tuple(value)
            for key, value in snapshot.separable_index.items()
        }
        self._augment_wordnet_expressions(
            token_nodes=token_nodes,
            expressions=expression_nodes,
            contiguous_index=contiguous_index,
            separable_index=separable_index,
        )

        def _wordnet_score(
            verb_token: MweTokenContext,
            particle_token: MweTokenContext,
            expression: MweExpressionContext,
        ) -> float:
            return self._wordnet_semantic_score(
                verb_token=verb_token,
                particle_token=particle_token,
                expression=expression,
            )

        def _trf_score(
            verb_token: MweTokenContext,
            particle_token: MweTokenContext,
            expression: MweExpressionContext,
        ) -> float:
            return self._trf_semantic_score(
                verb_token=verb_token,
                particle_token=particle_token,
                expression=expression,
                doc_token_vectors=doc_token_vectors,
            )

        detected = self._detector.detect(
            text=text,
            tokens=token_nodes,
            expressions=expression_nodes,
            contiguous_index=contiguous_index,
            separable_index=separable_index,
            wordnet_semantic_scorer=_wordnet_score,
            trf_semantic_scorer=_trf_score,
        )
        return [
            MweCandidate(
                expression_id=item.expression_id,
                canonical_form=item.canonical_form,
                expression_type=item.expression_type,
                is_separable=item.is_separable,
                span_start=item.span_start,
                span_end=item.span_end,
                token_start_index=item.token_start_index,
                token_end_index=item.token_end_index,
                surface=item.surface,
                sentence_text=item.sentence_text,
                detection_source=item.detection_source,
                semantic_score=item.semantic_score,
                semantic_boosted=item.semantic_boosted,
            )
            for item in detected
        ]

    def release_request_cache(self, request_id: str | None) -> None:
        cache_key = str(request_id or "").strip()
        if not cache_key:
            return
        with self._reference_cache_lock:
            self._request_payload_cache.pop(cache_key, None)

    def _resolve_request_payload(
        self,
        *,
        text: str,
        doc,
        request_id: str | None,
    ) -> tuple[list[MweTokenContext], dict[int, np.ndarray]]:
        cache_key = str(request_id or "").strip()
        if not cache_key:
            return self._build_token_nodes(text=text, doc=doc)
        text_key = str(text)
        doc_marker = id(doc)
        with self._reference_cache_lock:
            cached = self._request_payload_cache.get(cache_key)
            if (
                cached is not None
                and cached[0] == text_key
                and cached[1] == doc_marker
            ):
                self._request_payload_cache.move_to_end(cache_key)
                return cached[2], cached[3]
        token_nodes, doc_token_vectors = self._build_token_nodes(text=text, doc=doc)
        with self._reference_cache_lock:
            self._request_payload_cache[cache_key] = (
                text_key,
                doc_marker,
                token_nodes,
                doc_token_vectors,
            )
            self._request_payload_cache.move_to_end(cache_key)
            while len(self._request_payload_cache) > self._request_payload_cache_max_entries:
                self._request_payload_cache.popitem(last=False)
        return token_nodes, doc_token_vectors

    def _ensure_model(self) -> bool:
        if self._nlp is not None:
            return True
        if self._unavailable_reason is not None:
            return False
        if spacy is None:
            self._unavailable_reason = "spacy_unavailable"
            return False
        try:
            self._nlp = spacy.load(
                self._settings.spacy_trf_model_name,
                disable=["ner", "textcat"],
            )
            return True
        except Exception:
            self._unavailable_reason = "spacy_model_load_failed"
            self._nlp = None
            return False

    def _build_token_nodes(
        self,
        *,
        text: str,
        doc,
    ) -> tuple[list[MweTokenContext], dict[int, np.ndarray]]:
        filtered = [token for token in doc if not token.is_space and not token.is_punct]
        if not filtered:
            return [], {}
        positions = {int(token.i): idx for idx, token in enumerate(filtered)}
        token_nodes: list[MweTokenContext] = []
        for idx, token in enumerate(filtered):
            children_indices = tuple(
                int(positions[int(child.i)])
                for child in token.children
                if int(child.i) in positions and int(child.i) > int(token.i)
            )
            sentence_text = token.sent.text.strip() if token.sent is not None else text.strip()
            token_nodes.append(
                MweTokenContext(
                    index=idx,
                    doc_index=int(token.i),
                    text=str(token.text),
                    lower=str(token.lower_).strip().lower(),
                    lemma=str(token.lemma_ or token.lower_).strip().lower(),
                    pos=str(token.pos_ or "").strip().upper(),
                    dep=str(token.dep_ or "").strip().lower(),
                    start=int(token.idx),
                    end=int(token.idx + len(token)),
                    sentence_text=sentence_text,
                    children_indices=children_indices,
                )
            )
        return token_nodes, self._build_doc_token_vectors(doc)

    def _build_doc_token_vectors(self, doc) -> dict[int, np.ndarray]:
        trf_data = getattr(doc._, "trf_data", None)
        if trf_data is None:
            return {}
        ragged = getattr(trf_data, "last_hidden_layer_state", None)
        if ragged is None:
            return {}
        data = getattr(ragged, "data", None)
        lengths = getattr(ragged, "lengths", None)
        if data is None or lengths is None:
            return {}
        try:
            vectors = np.asarray(data, dtype=np.float32)
            piece_lengths = np.asarray(lengths, dtype=np.int32)
        except Exception:
            return {}
        if vectors.ndim != 2 or piece_lengths.ndim != 1 or vectors.shape[0] <= 0:
            return {}
        token_count = min(len(doc), int(piece_lengths.shape[0]))
        if token_count <= 0:
            return {}
        lengths_view = piece_lengths[:token_count]
        starts = np.zeros((token_count,), dtype=np.int64)
        if token_count > 1:
            starts[1:] = np.cumsum(lengths_view[: token_count - 1], dtype=np.int64)
        raw_ends = starts + lengths_view.astype(np.int64, copy=False)
        data_rows = int(vectors.shape[0])
        ends = np.clip(raw_ends, 0, data_rows)
        valid_mask = (lengths_view > 0) & (ends > starts)
        if not np.any(valid_mask):
            return {}

        valid_indices = np.nonzero(valid_mask)[0].astype(np.int64, copy=False)
        valid_starts = starts[valid_indices]
        valid_ends = ends[valid_indices]
        valid_lengths = (valid_ends - valid_starts).astype(np.float32, copy=False)

        prefix = np.vstack(
            [
                np.zeros((1, vectors.shape[1]), dtype=np.float32),
                np.cumsum(vectors, axis=0, dtype=np.float32),
            ]
        )
        segment_sums = prefix[valid_ends] - prefix[valid_starts]
        segment_means = segment_sums / valid_lengths.reshape(-1, 1)
        norms = np.linalg.norm(segment_means, axis=1)
        non_zero_norms = norms > 1e-12
        if not np.any(non_zero_norms):
            return {}

        normalized_vectors = segment_means[non_zero_norms] / norms[non_zero_norms].reshape(-1, 1)
        normalized_vectors = normalized_vectors.astype(np.float32, copy=False)
        output: dict[int, np.ndarray] = {}
        keep_indices = valid_indices[non_zero_norms]
        for pos, doc_index in enumerate(keep_indices):
            output[int(doc_index)] = normalized_vectors[pos]
        return output

    def _augment_wordnet_expressions(
        self,
        *,
        token_nodes: list[MweTokenContext],
        expressions: dict[int, MweExpressionContext],
        contiguous_index: dict[tuple[str, ...], tuple[int, ...]],
        separable_index: dict[tuple[str, str], tuple[int, ...]],
    ) -> None:
        if wn is None:
            return
        if not token_nodes:
            return
        current_min_id = min([0, *expressions.keys()])
        next_virtual_id = current_min_id - 1
        seen_pairs = set(separable_index.keys())
        gap = max(1, int(self._settings.second_pass_max_gap_tokens))
        for token in token_nodes:
            if str(token.pos or "").upper() not in {"VERB", "AUX"}:
                continue
            lemma = str(token.lemma or token.lower).strip().lower()
            if not lemma:
                continue
            window_end = min(len(token_nodes), token.index + gap + 2)
            for probe_index in range(token.index + 1, window_end):
                probe = token_nodes[probe_index]
                probe_pos = str(probe.pos or "").strip().upper()
                if probe_pos in {"VERB", "AUX"}:
                    break
                particle = str(probe.lower or "").strip().lower()
                if particle not in PHRASAL_PARTICLES:
                    continue
                gap_tokens = max(0, probe_index - token.index - 1)
                if not self._is_viable_phrasal_particle(
                    probe=probe,
                    particle=particle,
                    gap_tokens=gap_tokens,
                ):
                    continue
                pair = (lemma, particle)
                if pair in seen_pairs:
                    continue
                canonical = f"{lemma} {particle}"
                lemmas = self._wordnet_lemma_names(canonical)
                if not lemmas:
                    continue
                if not self._wordnet_supports_augmented_pair(
                    verb_lemma=lemma,
                    canonical_form=canonical,
                    phrase_lemmas=lemmas,
                ):
                    continue
                expression_id = next_virtual_id
                next_virtual_id -= 1
                expressions[expression_id] = MweExpressionContext(
                    expression_id=expression_id,
                    canonical_form=canonical,
                    expression_type="phrasal_verb",
                    is_separable=True,
                    max_gap_tokens=gap,
                    base_lemma=lemma,
                    particle=particle,
                    tokens=tuple(canonical.split()),
                )
                existing_for_pair = tuple(separable_index.get(pair, ()))
                separable_index[pair] = tuple([*existing_for_pair, expression_id])
                phrase_key = tuple(canonical.split())
                existing_for_phrase = tuple(contiguous_index.get(phrase_key, ()))
                contiguous_index[phrase_key] = tuple([*existing_for_phrase, expression_id])
                seen_pairs.add(pair)
                break

    def _is_viable_phrasal_particle(
        self,
        *,
        probe: MweTokenContext,
        particle: str,
        gap_tokens: int,
    ) -> bool:
        pos = str(probe.pos or "").strip().upper()
        dep = str(probe.dep or "").strip().lower()
        if pos and pos not in PHRASAL_PARTICLE_POS:
            return False
        if particle in WEAK_PHRASAL_PARTICLES:
            if pos != "PART" and dep not in PHRASAL_PARTICLE_DEP:
                return False
        if particle == "on" and gap_tokens > 0 and dep == "prep":
            return False
        return True

    def _wordnet_supports_augmented_pair(
        self,
        *,
        verb_lemma: str,
        canonical_form: str,
        phrase_lemmas: tuple[str, ...],
    ) -> bool:
        clean_verb = str(verb_lemma or "").strip().lower()
        if not clean_verb:
            return False
        if clean_verb in phrase_lemmas:
            return True
        phrase_synsets = self._wordnet_synsets(canonical_form)
        if not phrase_synsets:
            return False
        similarity = self._wordnet_wup_similarity(
            verb_lemma=clean_verb,
            canonical_form=canonical_form,
            phrase_synsets=phrase_synsets,
            phrase_lemmas=phrase_lemmas,
        )
        return float(similarity) >= 0.24

    def _wordnet_semantic_score(
        self,
        *,
        verb_token: MweTokenContext,
        particle_token: MweTokenContext,
        expression: MweExpressionContext,
    ) -> float:
        if expression.expression_type != "phrasal_verb":
            return 0.0
        canonical = str(expression.canonical_form or "").strip().lower()
        if not canonical:
            return 0.0
        verb_lemma = str(verb_token.lemma or verb_token.lower).strip().lower()
        lemmas = self._wordnet_lemma_names(canonical)
        fallback_score = self._legacy_wordnet_semantic_score(
            verb_lemma=verb_lemma,
            particle_token=particle_token,
            expression=expression,
            lemmas=lemmas,
        )
        if wn is None:
            return fallback_score

        phrase_synsets = self._wordnet_synsets(canonical)
        if not phrase_synsets:
            return fallback_score
        if not verb_lemma:
            return 0.0

        similarity = self._wordnet_wup_similarity(
            verb_lemma=verb_lemma,
            canonical_form=canonical,
            phrase_synsets=phrase_synsets,
            phrase_lemmas=lemmas,
        )
        if similarity <= 0.0:
            return 0.0

        score = float(similarity)
        if str(expression.particle).strip().lower() == str(particle_token.lower).strip().lower():
            score = min(0.99, score + 0.04)
        if "complete" in lemmas:
            score = max(score, min(0.99, similarity + 0.06))
        return max(0.0, float(score))

    def _legacy_wordnet_semantic_score(
        self,
        *,
        verb_lemma: str,
        particle_token: MweTokenContext,
        expression: MweExpressionContext,
        lemmas: tuple[str, ...] | None = None,
    ) -> float:
        resolved_lemmas = lemmas if lemmas is not None else self._wordnet_lemma_names(expression.canonical_form)
        if not resolved_lemmas:
            return 0.0
        score = 0.45
        if verb_lemma and verb_lemma in resolved_lemmas:
            score = max(score, 0.57)
        if str(expression.particle).strip().lower() == str(particle_token.lower).strip().lower():
            score = min(0.95, score + 0.08)
        if "complete" in resolved_lemmas:
            score = max(score, 0.72)
        return float(score)

    def _wordnet_lemma_names(self, canonical_form: str) -> tuple[str, ...]:
        key = str(canonical_form or "").strip().lower()
        if not key:
            return tuple()
        with self._reference_cache_lock:
            cached = self._wordnet_lemma_cache.get(key)
            if cached is not None:
                self._wordnet_lemma_cache.move_to_end(key)
                return cached
        if wn is None:
            lemmas = tuple()
        else:
            synsets = self._wordnet_synsets(key)
            lemma_values = sorted(
                {
                    str(lemma.name()).strip().lower()
                    for synset in synsets
                    for lemma in synset.lemmas()
                    if str(lemma.name()).strip()
                }
            )
            lemmas = tuple(lemma_values)
        with self._reference_cache_lock:
            self._wordnet_lemma_cache[key] = lemmas
            self._wordnet_lemma_cache.move_to_end(key)
            while len(self._wordnet_lemma_cache) > self._wordnet_cache_max_entries:
                self._wordnet_lemma_cache.popitem(last=False)
        return lemmas

    def _wordnet_synsets(self, query: str) -> tuple[object, ...]:
        key = str(query or "").strip().lower().replace(" ", "_")
        if not key or wn is None:
            return tuple()
        with self._reference_cache_lock:
            cached = self._wordnet_synset_cache.get(key)
            if cached is not None:
                self._wordnet_synset_cache.move_to_end(key)
                return cached
        try:
            synsets = tuple(wn.synsets(key, pos=wn.VERB))
        except Exception:
            synsets = tuple()
        with self._reference_cache_lock:
            self._wordnet_synset_cache[key] = synsets
            self._wordnet_synset_cache.move_to_end(key)
            while len(self._wordnet_synset_cache) > self._wordnet_synset_cache_max_entries:
                self._wordnet_synset_cache.popitem(last=False)
        return synsets

    def _wordnet_wup_similarity(
        self,
        *,
        verb_lemma: str,
        canonical_form: str,
        phrase_synsets: tuple[object, ...],
        phrase_lemmas: tuple[str, ...],
    ) -> float:
        cache_key = (str(verb_lemma).strip().lower(), str(canonical_form).strip().lower())
        if not cache_key[0] or not cache_key[1]:
            return 0.0
        with self._reference_cache_lock:
            cached = self._wordnet_similarity_cache.get(cache_key)
            if cached is not None:
                self._wordnet_similarity_cache.move_to_end(cache_key)
                return float(cached)

        verb_synsets = self._wordnet_synsets(cache_key[0])
        if not verb_synsets or not phrase_synsets:
            score = 0.0
        else:
            target_synsets: list[object] = list(phrase_synsets)
            for lemma in phrase_lemmas[:6]:
                normalized = str(lemma).strip().lower().replace("_", " ")
                if not normalized or normalized == cache_key[0]:
                    continue
                target_synsets.extend(self._wordnet_synsets(normalized))
            deduped_targets: list[object] = []
            seen_target_ids: set[int] = set()
            for item in target_synsets:
                marker = id(item)
                if marker in seen_target_ids:
                    continue
                seen_target_ids.add(marker)
                deduped_targets.append(item)
            score = 0.0
            for left in verb_synsets:
                for right in deduped_targets:
                    current = self._safe_wup_similarity(left, right)
                    if current > score:
                        score = current

        with self._reference_cache_lock:
            self._wordnet_similarity_cache[cache_key] = float(score)
            self._wordnet_similarity_cache.move_to_end(cache_key)
            while len(self._wordnet_similarity_cache) > self._wordnet_similarity_cache_max_entries:
                self._wordnet_similarity_cache.popitem(last=False)
        return float(score)

    def _safe_wup_similarity(self, left_synset: object, right_synset: object) -> float:
        try:
            scorer = getattr(left_synset, "wup_similarity", None)
            if scorer is None:
                return 0.0
            score = scorer(right_synset)
        except Exception:
            return 0.0
        if score is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            return 0.0

    def _trf_semantic_score(
        self,
        *,
        verb_token: MweTokenContext,
        particle_token: MweTokenContext,
        expression: MweExpressionContext,
        doc_token_vectors: dict[int, np.ndarray],
    ) -> float:
        if expression.expression_type != "phrasal_verb":
            return 0.0
        phrase_vector = self._build_phrase_vector(
            start_doc_index=verb_token.doc_index,
            end_doc_index=particle_token.doc_index,
            doc_token_vectors=doc_token_vectors,
        )
        if phrase_vector is None:
            return 0.0
        reference_vector = self._reference_trf_vector(expression)
        if reference_vector is None:
            return 0.0
        return float(self._cosine_similarity(phrase_vector, reference_vector))

    def _build_phrase_vector(
        self,
        *,
        start_doc_index: int,
        end_doc_index: int,
        doc_token_vectors: dict[int, np.ndarray],
    ) -> np.ndarray | None:
        if end_doc_index < start_doc_index:
            start_doc_index, end_doc_index = end_doc_index, start_doc_index
        vectors = [
            doc_token_vectors[item]
            for item in range(int(start_doc_index), int(end_doc_index) + 1)
            if item in doc_token_vectors
        ]
        if not vectors:
            return None
        stacked = np.vstack(vectors).astype(np.float32, copy=False)
        return self._normalize_vector(stacked.mean(axis=0))

    def _reference_trf_vector(self, expression: MweExpressionContext) -> np.ndarray | None:
        key = str(expression.canonical_form or "").strip().lower()
        if not key:
            return None
        with self._reference_cache_lock:
            cached = self._reference_vector_cache.get(key)
            if cached is not None:
                self._reference_vector_cache.move_to_end(key)
                return cached

        nlp = self._nlp
        if nlp is None:
            return None
        probe_text = self._build_reference_probe_text(expression)
        try:
            ref_doc = nlp(probe_text)
        except Exception:
            return None

        ref_vectors = self._build_doc_token_vectors(ref_doc)
        ref_tokens = [token for token in ref_doc if not token.is_space and not token.is_punct]
        if not ref_tokens or not ref_vectors:
            return None

        expression_terms = tuple(
            token.strip().lower()
            for token in expression.canonical_form.split(" ")
            if token.strip()
        )
        phrase_vector: np.ndarray | None = None
        span = self._find_span(ref_tokens=ref_tokens, terms=expression_terms)
        if span is not None:
            start_idx, end_idx = span
            phrase_vector = self._build_phrase_vector(
                start_doc_index=int(ref_tokens[start_idx].i),
                end_doc_index=int(ref_tokens[end_idx].i),
                doc_token_vectors=ref_vectors,
            )
        if phrase_vector is None:
            phrase_vector = self._build_phrase_vector(
                start_doc_index=int(ref_tokens[0].i),
                end_doc_index=int(ref_tokens[-1].i),
                doc_token_vectors=ref_vectors,
            )
        if phrase_vector is None:
            return None

        with self._reference_cache_lock:
            self._reference_vector_cache[key] = phrase_vector
            self._reference_vector_cache.move_to_end(key)
            while len(self._reference_vector_cache) > self._reference_cache_max_entries:
                self._reference_vector_cache.popitem(last=False)
        return phrase_vector

    def _build_reference_probe_text(self, expression: MweExpressionContext) -> str:
        canonical = str(expression.canonical_form or "").strip().lower()
        lemmas = self._wordnet_lemma_names(canonical)
        preferred = ", ".join(list(lemmas)[:4]) if lemmas else ""
        if preferred:
            return f"to {canonical} means {preferred}"
        return f"to {canonical}"

    def _find_span(self, *, ref_tokens, terms: tuple[str, ...]) -> tuple[int, int] | None:
        if not terms:
            return None
        lowered = [str(token.lower_).strip().lower() for token in ref_tokens]
        total = len(lowered)
        size = len(terms)
        for start in range(total):
            end = start + size
            if end > total:
                break
            if tuple(lowered[start:end]) == terms:
                return start, end - 1
        return None

    def _normalize_vector(self, vector: np.ndarray) -> np.ndarray | None:
        arr = np.asarray(vector, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return None
        norm = float(np.linalg.norm(arr))
        if norm <= 1e-12:
            return None
        return arr / norm

    def _cosine_similarity(self, left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape:
            return 0.0
        score = float(np.dot(left, right))
        if score < -1.0:
            return -1.0
        if score > 1.0:
            return 1.0
        return score
