from __future__ import annotations

from typing import Any

from core.domain.services import TextProcessor


class ParseTableBuilder:
    """Build parse result rows for UI and API DTO payloads."""

    def __init__(self, *, text_processor: TextProcessor) -> None:
        self._text_processor = text_processor

    def build_table(
        self,
        parsed: dict[str, Any],
        *,
        known_lemmas: set[str],
    ) -> list[list[str]]:
        table: list[list[str]] = []
        row_index = 1

        for item in parsed["tokens"]:
            raw_categories = item.get("categories")
            categories_for_rows: list[str] = []
            if isinstance(raw_categories, (list, tuple)):
                seen: set[str] = set()
                for raw_category in raw_categories:
                    category = str(raw_category).strip()
                    if not category or category == "-":
                        continue
                    key = category.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    categories_for_rows.append(category)
            elif raw_categories is not None:
                category = str(raw_categories).strip()
                if category and category != "-":
                    categories_for_rows.append(category)

            if not categories_for_rows:
                categories_for_rows = ["-"]
            elif not self._text_processor.should_split_homonym_rows(categories_for_rows):
                categories_for_rows = [", ".join(categories_for_rows)]

            bert_score = item["bert_score"] if item["bert_score"] is not None else ""
            lemma = str(item["lemma"])
            lemma_normalized = self._text_processor.normalize_lexeme(lemma)
            known_in_db = bool(lemma_normalized and lemma_normalized in known_lemmas)

            for category in categories_for_rows:
                table.append(
                    [
                        str(row_index),
                        str(item["token"]),
                        str(item["normalized"]),
                        lemma,
                        category,
                        str(item["match_source"]),
                        str(item["matched_form"]),
                        str(bert_score),
                        "yes" if known_in_db else "no",
                    ]
                )
                row_index += 1

        return table

    def append_occurrence_rows(
        self,
        table: list[list[str]],
        *,
        occurrences: object,
        source_label: str,
        known_terms: set[str] | None = None,
    ) -> list[list[str]]:
        if not isinstance(occurrences, list):
            return table

        normalized_known_terms = {
            normed
            for item in (known_terms or set())
            if (normed := self._text_processor.normalize_term(item))
        }

        row_index = len(table) + 1
        seen: set[tuple[str, str, str]] = set()

        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue

            expression_type = str(occurrence.get("expression_type", "")).strip().lower().replace("-", "_")
            if expression_type not in {"phrasal_verb", "idiom"}:
                continue

            canonical = self._text_processor.normalize_term(
                occurrence.get("canonical_form") or occurrence.get("surface") or ""
            )
            canonical = self._text_processor.canonicalize_expression(
                canonical,
                expression_type=expression_type,
            )
            if not canonical:
                continue

            marker = (canonical, expression_type, source_label)
            if marker in seen:
                continue
            seen.add(marker)

            category = "Phrasal Verb" if expression_type == "phrasal_verb" else "Idiom"
            token_value = str(occurrence.get("surface") or canonical).strip() or canonical
            lemma_value = (
                canonical.split(" ", 1)[0]
                if expression_type == "phrasal_verb" and " " in canonical
                else canonical
            )
            usage_label = str(occurrence.get("usage_label", "")).strip().lower()
            matched_form = expression_type
            if usage_label:
                matched_form = f"{matched_form}:{usage_label}"

            score_text = ""
            raw_score = occurrence.get("score")
            if raw_score is not None:
                try:
                    score_text = str(round(float(raw_score), 4))
                except (TypeError, ValueError):
                    score_text = str(raw_score)

            known_in_db = "yes" if canonical in normalized_known_terms else "no"
            resolved_source_label = str(occurrence.get("source") or source_label).strip() or str(source_label)

            table.append(
                [
                    str(row_index),
                    token_value,
                    canonical,
                    lemma_value,
                    category,
                    resolved_source_label,
                    matched_form,
                    score_text,
                    known_in_db,
                ]
            )
            row_index += 1

        return table

    def append_heuristic_phrasal_rows(
        self,
        table: list[list[str]],
        *,
        phrasal_verbs: list[str],
        known_terms: set[str] | None = None,
    ) -> list[list[str]]:
        if not phrasal_verbs:
            return table

        normalized_known_terms = {
            normed
            for item in (known_terms or set())
            if (normed := self._text_processor.normalize_term(item))
        }

        existing_phrasal_forms = {
            normed
            for row in table
            if len(row) > 4
            and str(row[4]).strip().casefold() == "phrasal verb"
            and len(row) > 2
            and (normed := self._text_processor.normalize_term(row[2]))
        }

        row_index = len(table) + 1
        for candidate in phrasal_verbs:
            canonical = self._text_processor.canonicalize_expression(
                candidate,
                expression_type="phrasal_verb",
            )
            if not canonical:
                continue
            if canonical in existing_phrasal_forms:
                continue
            existing_phrasal_forms.add(canonical)

            lemma_value = canonical.split(" ", 1)[0] if " " in canonical else canonical
            known_value = "yes" if canonical in normalized_known_terms else "no"
            table.append(
                [
                    str(row_index),
                    canonical,
                    canonical,
                    lemma_value,
                    "Phrasal Verb",
                    "phrasal_heuristic",
                    "adjacent_verb_particle",
                    "",
                    known_value,
                ]
            )
            row_index += 1

        return table
