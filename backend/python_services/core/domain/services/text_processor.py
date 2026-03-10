from __future__ import annotations

import re
from typing import Any


WORD_RE = re.compile(r"^[a-z]+(?:[-'][a-z]+)*$")
SAFE_TERM_RE = re.compile(r"^[a-z]+(?:[-'][a-z]+)*(?: [a-z]+(?:[-'][a-z]+)*)*$")
WEIRD_UNICODE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# High-frequency English function words that are not meaningful vocabulary items.
_AUTO_ADD_BLOCKLIST: frozenset[str] = frozenset({
    "a", "an", "the",
    "i", "me", "my", "myself",
    "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves",
    "this", "that", "these", "those",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had",
    "do", "does", "did",
    "and", "but", "or", "nor", "so", "yet", "for",
    "of", "in", "on", "at", "by", "to", "as", "if",
    "not", "no",
})
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
PHRASAL_VERB_POS = {"VERB", "AUX"}
PHRASAL_PARTICLE_POS = {"ADP", "PART", "ADV"}
PHRASAL_PARTICLE_DEP = {"prt", "compound:prt"}
STOPWORD_PARTICLE_CATEGORIES = {"preposition", "particle", "phrasal verb"}
PHRASAL_MAX_GAP_TOKENS = 4
IRREGULAR_VERB_HEADS = {
    "ran": "run",
    "run": "run",
    "went": "go",
    "gone": "go",
    "took": "take",
    "taken": "take",
    "gave": "give",
    "given": "give",
    "did": "do",
    "done": "do",
    "saw": "see",
    "seen": "see",
    "came": "come",
    "come": "come",
    "left": "leave",
    "made": "make",
    "said": "say",
    "told": "tell",
    "thought": "think",
    "brought": "bring",
    "bought": "buy",
    "caught": "catch",
    "felt": "feel",
    "found": "find",
    "heard": "hear",
    "held": "hold",
    "kept": "keep",
    "knew": "know",
    "met": "meet",
    "paid": "pay",
    "read": "read",
    "sat": "sit",
    "sold": "sell",
    "sent": "send",
    "spoke": "speak",
    "spoken": "speak",
    "spent": "spend",
    "stood": "stand",
    "taught": "teach",
    "wrote": "write",
    "written": "write",
    "called": "call",
    "got": "get",
    "gotten": "get",
    "fell": "fall",
    "fallen": "fall",
    "broke": "break",
    "broken": "break",
    "woke": "wake",
    "woken": "wake",
    "won": "win",
    "lost": "lose",
    "built": "build",
    "dealt": "deal",
    "wore": "wear",
    "worn": "wear",
    "threw": "throw",
    "thrown": "throw",
    "grew": "grow",
    "grown": "grow",
    "drew": "draw",
    "drawn": "draw",
    "blew": "blow",
    "blown": "blow",
    "drove": "drive",
    "driven": "drive",
}
POS_CATEGORY_HINTS = {
    "NOUN": "Noun",
    "PROPN": "Noun",
    "VERB": "Verb",
    "AUX": "Verb",
    "ADJ": "Adjective",
    "ADV": "Adverb",
    "PRON": "Pronoun",
    "ADP": "Preposition",
    "DET": "Determiner",
    "CCONJ": "Coordinating conjunction",
    "SCONJ": "Subordinating conjunction",
    "INTJ": "Interjection",
    "NUM": "Numeral",
    "PART": "Particle",
}
POS_DISAMBIGUATION_CATEGORIES = {value.casefold() for value in POS_CATEGORY_HINTS.values()}


class TextProcessor:
    def unique(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            output.append(item)
        return output

    def normalize_lexeme(self, raw: str | None) -> str:
        if raw is None:
            return ""
        value = str(raw).strip().lower()
        if not value:
            return ""
        if (
            value.endswith("s")
            and not value.endswith("ss")
            and len(value) > 3
            and value not in {"this", "these", "those", "news", "always"}
        ):
            value = value[:-1]
        return value

    def normalize_term(self, raw: object) -> str:
        return re.sub(r"\s+", " ", str(raw or "").strip().lower())

    def normalize_verb_head(self, raw: object) -> str:
        value = self.normalize_term(raw)
        if not value:
            return ""
        head = value.split(" ", 1)[0]
        if not WORD_RE.fullmatch(head):
            return head
        irregular = IRREGULAR_VERB_HEADS.get(head)
        if irregular:
            return irregular
        if head.endswith("ied") and len(head) > 4:
            return f"{head[:-3]}y"
        if head.endswith("ies") and len(head) > 4:
            return f"{head[:-3]}y"
        if head.endswith("ing") and len(head) > 5:
            stem = head[:-3]
            if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in {"s", "l", "z"}:
                stem = stem[:-1]
            if stem.endswith(("at", "bl", "iz")):
                return f"{stem}e"
            return stem
        if head.endswith("ed") and len(head) > 4:
            stem = head[:-2]
            if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in {"s", "l", "z"}:
                stem = stem[:-1]
            if stem.endswith("i"):
                return f"{stem[:-1]}y"
            return stem
        if head.endswith("es") and len(head) > 4:
            if head.endswith(("oes", "ses", "xes", "zes", "ches", "shes")):
                return head[:-2]
            return head[:-1]
        if head.endswith("s") and len(head) > 3 and head not in {"this", "these", "those"}:
            return head[:-1]
        return head

    def _looks_like_verb_form(self, word: str) -> bool:
        """True only if word is unambiguously an inflected verb form.

        Used by canonicalize_expression to guard idiom first-word normalization
        so that noun/adjective-initial idioms like 'blessing in disguise' are not
        corrupted. Phrasal verbs always start with a verb and bypass this check.
        """
        if not word or not WORD_RE.fullmatch(word):
            return False
        if word in IRREGULAR_VERB_HEADS:
            return True
        if (word.endswith("ied") or word.endswith("ies")) and len(word) > 4:
            return True
        return False

    def canonicalize_expression(self, raw: object, *, expression_type: str = "") -> str:
        value = self.normalize_term(raw)
        if not value:
            return ""
        parts = [part for part in value.split(" ") if part]
        if not parts:
            return ""
        normalized_type = str(expression_type or "").strip().lower().replace("-", "_")
        if normalized_type == "phrasal_verb" and len(parts) > 1:
            # Phrasal verbs always start with a verb — normalize unconditionally.
            parts[0] = self.normalize_verb_head(parts[0])
            return " ".join(parts)
        if normalized_type == "idiom" and len(parts) > 1:
            # Idioms may start with articles, prepositions, or noun forms.
            # Only normalize the first word if it is unambiguously an inflected verb.
            if self._looks_like_verb_form(parts[0]):
                parts[0] = self.normalize_verb_head(parts[0])
            return " ".join(parts)
        if len(parts) > 1 and parts[-1] in PHRASAL_PARTICLES:
            parts[0] = self.normalize_verb_head(parts[0])
            return " ".join(parts)
        return value

    def extract_lexemes(self, tokens: list[dict[str, Any]]) -> list[str]:
        lexemes: list[str] = []
        for token_info in tokens:
            normalized = str(token_info.get("normalized", "")).strip().lower()
            pos_tag = str(token_info.get("pos", "")).strip().upper()
            lemma = self.normalize_lexeme(str(token_info.get("lemma", "")))
            candidate = lemma or self.normalize_lexeme(normalized)
            if not candidate:
                continue
            if not WORD_RE.fullmatch(candidate):
                continue
            lexemes.append(candidate)
        return self.unique(lexemes)

    def extract_phrasal_verbs(self, tokens: list[dict[str, Any]]) -> list[str]:
        phrasal_verbs: list[str] = []
        total = len(tokens)
        for idx in range(total - 1):
            current = tokens[idx]
            verb = self.normalize_lexeme(str(current.get("lemma", "") or current.get("normalized", "")))

            if not verb:
                continue
            if not WORD_RE.fullmatch(verb):
                continue
            pos = str(current.get("pos", "")).strip().upper()
            if pos and pos not in PHRASAL_VERB_POS:
                continue
            window_end = min(total, idx + PHRASAL_MAX_GAP_TOKENS + 2)
            for probe in range(idx + 1, window_end):
                probe_token = tokens[probe]
                probe_pos = str(probe_token.get("pos", "")).strip().upper()
                if probe_pos in PHRASAL_VERB_POS:
                    break
                particle = str(probe_token.get("normalized", "")).strip().lower()
                if particle not in PHRASAL_PARTICLES:
                    continue
                gap_tokens = max(0, probe - idx - 1)
                if not self._is_valid_phrasal_particle_token(
                    probe_token,
                    particle=particle,
                    gap_tokens=gap_tokens,
                ):
                    continue
                # First particle found. Check if a second particle follows
                # to form a three-word phrasal verb (e.g., "look forward to").
                second_particle: str | None = None
                for second_probe in range(probe + 1, min(total, probe + 3)):
                    second_token = tokens[second_probe]
                    if str(second_token.get("pos", "")).strip().upper() in PHRASAL_VERB_POS:
                        break
                    second_p = str(second_token.get("normalized", "")).strip().lower()
                    if second_p not in PHRASAL_PARTICLES or second_p == particle:
                        continue
                    second_gap = max(0, second_probe - probe - 1)
                    if self._is_valid_phrasal_particle_token(
                        second_token,
                        particle=second_p,
                        gap_tokens=second_gap,
                    ):
                        second_particle = second_p
                        break
                if second_particle:
                    phrasal_candidate = self.canonicalize_expression(
                        f"{verb} {particle} {second_particle}",
                        expression_type="phrasal_verb",
                    )
                else:
                    phrasal_candidate = self.canonicalize_expression(
                        f"{verb} {particle}",
                        expression_type="phrasal_verb",
                    )
                if phrasal_candidate:
                    phrasal_verbs.append(phrasal_candidate)
                break
        return self.unique(phrasal_verbs)

    def format_sync_message(self, added: list[str], already_existed: list[str]) -> str:
        lines = ["added:"]
        if added:
            lines.extend([f"- {item}" for item in added])
        lines.append("already existed:")
        if already_existed:
            lines.extend([f"- {item}" for item in already_existed])
        return "\n".join(lines)

    def allow_auto_add(self, candidate: str, *, suggested_category: str = "") -> bool:
        cleaned = candidate.strip().lower()
        if not cleaned:
            return False
        if cleaned in _AUTO_ADD_BLOCKLIST and not self._is_syncable_stopword(
            cleaned,
            suggested_category=suggested_category,
        ):
            return False
        if len(cleaned) < 2:
            return False
        if cleaned.isdigit():
            return False
        if WEIRD_UNICODE_RE.search(cleaned):
            return False
        return SAFE_TERM_RE.fullmatch(cleaned) is not None

    def _is_syncable_stopword(self, candidate: str, *, suggested_category: str) -> bool:
        clean_candidate = str(candidate or "").strip().lower()
        if clean_candidate not in PHRASAL_PARTICLES:
            return False
        categories = [item.strip().casefold() for item in str(suggested_category or "").split(",")]
        return any(
            item in STOPWORD_PARTICLE_CATEGORIES
            for item in categories
            if item
        )

    def should_split_homonym_rows(self, categories: list[str]) -> bool:
        if len(categories) < 2:
            return False
        pos_like = {
            str(category).strip().casefold()
            for category in categories
            if str(category).strip().casefold() in POS_DISAMBIGUATION_CATEGORIES
        }
        return len(pos_like) >= 2

    def category_from_token(self, token: dict[str, Any]) -> str:
        categories: list[str] = []
        raw_categories = token.get("categories")
        if isinstance(raw_categories, (list, tuple)):
            for raw_category in raw_categories:
                category = str(raw_category).strip()
                if category and category != "-":
                    categories.append(category)

        pos_tag = str(token.get("pos", "")).strip().upper()
        hinted_category = POS_CATEGORY_HINTS.get(pos_tag, "")
        if categories:
            hinted_casefold = hinted_category.casefold()
            if hinted_casefold:
                for category in categories:
                    if category.casefold() == hinted_casefold:
                        return category
            return categories[0]
        return hinted_category

    def build_candidate_categories(
        self,
        parsed_tokens: list[dict[str, Any]],
        phrasal_verbs: list[str],
        *,
        auto_add_category: str,
    ) -> dict[str, str]:
        categories: dict[str, str] = {}
        for token in parsed_tokens:
            normalized = self.normalize_lexeme(str(token.get("normalized", "")))
            lemma = self.normalize_lexeme(str(token.get("lemma", "")))
            candidate = lemma or normalized
            if not candidate:
                continue
            category = self.category_from_token(token)
            if not category:
                continue
            categories.setdefault(candidate, category)

        for phrase in phrasal_verbs:
            clean_phrase = self.canonicalize_expression(
                phrase,
                expression_type="phrasal_verb",
            )
            if not clean_phrase:
                continue
            categories.setdefault(clean_phrase, "Phrasal Verb")
        return categories

    def extract_occurrence_sync_candidates(
        self,
        occurrences: object,
        *,
        auto_add_category: str,
    ) -> tuple[list[str], dict[str, str]]:
        if not isinstance(occurrences, list):
            return [], {}
        candidates: list[str] = []
        candidate_categories: dict[str, str] = {}
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            raw_candidate = str(
                occurrence.get("canonical_form") or occurrence.get("surface") or ""
            ).strip().lower()
            if not raw_candidate:
                continue
            expression_type = str(occurrence.get("expression_type", "")).strip().lower()
            candidate = self.canonicalize_expression(
                raw_candidate,
                expression_type=expression_type,
            )
            if not candidate:
                continue
            if expression_type == "phrasal_verb":
                category = "Phrasal Verb"
            elif expression_type == "idiom":
                category = "Idiom"
            else:
                usage_label = str(occurrence.get("usage_label", "")).strip().lower()
                category = "Idiom" if usage_label == "idiomatic" else auto_add_category
            candidates.append(candidate)
            candidate_categories.setdefault(candidate, category)
        return self.unique(candidates), candidate_categories

    def _is_valid_phrasal_particle_token(
        self,
        token_info: dict[str, Any],
        *,
        particle: str,
        gap_tokens: int,
    ) -> bool:
        pos = str(token_info.get("pos", "")).strip().upper()
        dep = str(token_info.get("dep", "")).strip().lower()
        if pos and pos not in PHRASAL_PARTICLE_POS:
            return False
        if particle in WEAK_PHRASAL_PARTICLES:
            if pos != "PART" and dep not in PHRASAL_PARTICLE_DEP:
                return False
        if particle == "on" and gap_tokens > 0:
            if dep == "prep":
                return False
            if not dep and pos == "ADP":
                return False
        return True


DEFAULT_TEXT_PROCESSOR = TextProcessor()
