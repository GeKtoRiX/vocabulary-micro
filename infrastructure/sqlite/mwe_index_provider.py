from __future__ import annotations

from dataclasses import dataclass
import hashlib
from threading import RLock
from types import MappingProxyType
from typing import Callable, Iterable

from .text_utils import TOKEN_PATTERN, normalize_whitespace


@dataclass(frozen=True)
class MweExpressionRecord:
    expression_id: int
    canonical_form: str
    tokens: tuple[str, ...]
    expression_type: str
    base_lemma: str
    particle: str
    is_separable: bool
    max_gap_tokens: int


@dataclass(frozen=True)
class MweSenseRecord:
    sense_id: int
    expression_id: int
    sense_key: str
    gloss: str
    usage_label: str
    example: str
    priority: int
    embedding: tuple[float, ...] | None

    @property
    def text_for_embedding(self) -> str:
        if self.example:
            return f"{self.gloss} Example: {self.example}"
        return self.gloss


@dataclass(frozen=True)
class MweIndexSnapshot:
    version: int
    expressions: MappingProxyType[int, MweExpressionRecord]
    senses_by_expression: MappingProxyType[int, tuple[MweSenseRecord, ...]]
    contiguous_index: MappingProxyType[tuple[str, ...], tuple[int, ...]]
    separable_index: MappingProxyType[tuple[str, str], tuple[int, ...]]
    candidate_hash: str
    model_name: str
    model_revision: str | None


class MweIndexProvider:
    def __init__(
        self,
        *,
        version_loader: Callable[[], int],
        expression_loader: Callable[[], list[dict[str, object]]],
        sense_loader: Callable[[], list[dict[str, object]]],
        embedding_loader: Callable[[str, str | None], dict[int, tuple[float, ...]]],
    ) -> None:
        self._version_loader = version_loader
        self._expression_loader = expression_loader
        self._sense_loader = sense_loader
        self._embedding_loader = embedding_loader
        self._lock = RLock()
        self._snapshot: MweIndexSnapshot | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = None

    def get_snapshot(
        self,
        *,
        model_name: str,
        model_revision: str | None,
    ) -> tuple[MweIndexSnapshot, bool]:
        current_version = self._version_loader()
        with self._lock:
            cached = self._snapshot
            if (
                cached is not None
                and cached.version == current_version
                and cached.model_name == model_name
                and cached.model_revision == model_revision
            ):
                return cached, True
            snapshot = self._build_snapshot(
                version=current_version,
                model_name=model_name,
                model_revision=model_revision,
            )
            self._snapshot = snapshot
            return snapshot, False

    def _build_snapshot(
        self,
        *,
        version: int,
        model_name: str,
        model_revision: str | None,
    ) -> MweIndexSnapshot:
        expression_rows = self._expression_loader()
        sense_rows = self._sense_loader()
        sense_embeddings = self._embedding_loader(model_name, model_revision)

        expressions: dict[int, MweExpressionRecord] = {}
        contiguous_index: dict[tuple[str, ...], list[int]] = {}
        separable_index: dict[tuple[str, str], list[int]] = {}

        for row in expression_rows:
            canonical_form = normalize_whitespace(str(row.get("canonical_form", ""))).lower()
            if not canonical_form:
                continue
            tokens = tuple(token.lower() for token in TOKEN_PATTERN.findall(canonical_form))
            if not tokens:
                continue
            expression_id = int(row.get("id", 0))
            expression = MweExpressionRecord(
                expression_id=expression_id,
                canonical_form=canonical_form,
                tokens=tokens,
                expression_type=str(row.get("expression_type", "idiom")),
                base_lemma=str(row.get("base_lemma", "")).strip().lower(),
                particle=str(row.get("particle", "")).strip().lower(),
                is_separable=bool(int(row.get("is_separable", 0))),
                max_gap_tokens=max(1, int(row.get("max_gap_tokens", 4))),
            )
            expressions[expression_id] = expression
            contiguous_index.setdefault(tokens, []).append(expression_id)
            if expression.is_separable:
                pair: tuple[str, str] | None = None
                if expression.base_lemma and expression.particle:
                    pair = (expression.base_lemma, expression.particle)
                elif expression.expression_type == "phrasal_verb" and len(tokens) >= 2:
                    pair = (tokens[0], tokens[-1])
                if pair is not None:
                    separable_index.setdefault(pair, []).append(expression_id)

        senses_by_expression: dict[int, list[MweSenseRecord]] = {}
        for row in sense_rows:
            expression_id = int(row.get("expression_id", 0))
            if expression_id not in expressions:
                continue
            sense_id = int(row.get("id", 0))
            sense = MweSenseRecord(
                sense_id=sense_id,
                expression_id=expression_id,
                sense_key=str(row.get("sense_key", "")).strip(),
                gloss=str(row.get("gloss", "")).strip(),
                usage_label=str(row.get("usage_label", "idiomatic")).strip().lower() or "idiomatic",
                example=str(row.get("example", "")).strip(),
                priority=int(row.get("priority", 0)),
                embedding=sense_embeddings.get(sense_id),
            )
            senses_by_expression.setdefault(expression_id, []).append(sense)

        frozen_senses = {
            expression_id: tuple(
                sorted(items, key=lambda item: (item.priority, item.sense_id))
            )
            for expression_id, items in senses_by_expression.items()
        }
        frozen_contiguous = {
            key: tuple(sorted(set(expression_ids)))
            for key, expression_ids in contiguous_index.items()
        }
        frozen_separable = {
            key: tuple(sorted(set(expression_ids)))
            for key, expression_ids in separable_index.items()
        }

        return MweIndexSnapshot(
            version=version,
            expressions=MappingProxyType(expressions),
            senses_by_expression=MappingProxyType(frozen_senses),
            contiguous_index=MappingProxyType(frozen_contiguous),
            separable_index=MappingProxyType(frozen_separable),
            candidate_hash=self._candidate_hash(
                expressions=expressions.values(),
                senses=frozen_senses.values(),
                model_name=model_name,
                model_revision=model_revision,
            ),
            model_name=model_name,
            model_revision=model_revision,
        )

    def _candidate_hash(
        self,
        *,
        expressions: Iterable[MweExpressionRecord],
        senses: Iterable[tuple[MweSenseRecord, ...]],
        model_name: str,
        model_revision: str | None,
    ) -> str:
        chunks: list[str] = [model_name, model_revision or ""]
        for item in sorted(expressions, key=lambda value: value.expression_id):
            chunks.append(
                "|".join(
                    [
                        str(item.expression_id),
                        item.canonical_form,
                        item.expression_type,
                        "1" if item.is_separable else "0",
                        str(item.max_gap_tokens),
                    ]
                )
            )
        for bucket in senses:
            for sense in bucket:
                chunks.append(
                    "|".join(
                        [
                            str(sense.expression_id),
                            str(sense.sense_id),
                            sense.sense_key,
                            sense.usage_label,
                            sense.gloss,
                            sense.example,
                        ]
                    )
                )
        joined = "\x1f".join(chunks)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()
