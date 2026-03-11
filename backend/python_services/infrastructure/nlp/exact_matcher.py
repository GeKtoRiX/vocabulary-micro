from __future__ import annotations

from backend.python_services.core.domain import PhraseMatchRecord, TokenRecord

from .index_provider import LexiconIndexSnapshot


class ExactMatcherStage:
    def apply_token_matching(
        self,
        tokens: list[TokenRecord],
        snapshot: LexiconIndexSnapshot,
    ) -> None:
        for token_info in tokens:
            categories = list(snapshot.single_word.get(token_info.normalized, ()))
            if categories:
                token_info.categories = categories
                token_info.known = True
                token_info.match_source = "exact"
                token_info.matched_form = token_info.normalized

    def apply_phrase_matching(
        self,
        text: str,
        tokens: list[TokenRecord],
        snapshot: LexiconIndexSnapshot,
    ) -> list[PhraseMatchRecord]:
        normalized_tokens = [item.normalized for item in tokens]
        phrase_matches: list[PhraseMatchRecord] = []
        for start_idx, end_idx, categories, normalized in snapshot.phrase_matcher.longest_matches(normalized_tokens):
            phrase_matches.append(
                PhraseMatchRecord(
                    phrase=text[tokens[start_idx].start : tokens[end_idx].end],
                    normalized=normalized,
                    start_token_index=start_idx,
                    end_token_index=end_idx,
                    categories=tuple(categories),
                )
            )

            for token_idx in range(start_idx, end_idx + 1):
                token = tokens[token_idx]
                merged = sorted(set(token.categories).union(categories))
                token.categories = merged
                if not token.known:
                    token.match_source = "exact_phrase"
                    token.matched_form = normalized
                token.known = True
        return phrase_matches


