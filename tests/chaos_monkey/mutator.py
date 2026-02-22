"""Text mutation rules for generating varied test inputs."""

import random
import re
from dataclasses import dataclass


@dataclass
class MutationResult:
    """Result of applying mutations to text."""

    original: str
    mutated: str
    mutations_applied: list[str]


class TextMutator:
    """Applies various mutations to test inputs to find edge cases."""

    # --- STT (Speech-to-Text) simulation dictionaries ---

    # Bidirectional homophones
    STT_HOMOPHONES: dict[str, list[str]] = {
        "two": ["to", "too"],
        "to": ["two", "too"],
        "too": ["two", "to"],
        "one": ["won"],
        "won": ["one"],
        "no": ["know"],
        "know": ["no"],
        "plain": ["plane"],
        "plane": ["plain"],
        "for": ["four", "fore"],
        "four": ["for", "fore"],
        "flour": ["flower"],
        "flower": ["flour"],
        "whole": ["hole"],
        "hole": ["whole"],
        "wrap": ["rap"],
        "rap": ["wrap"],
        "berry": ["bury"],
        "bury": ["berry"],
        "meat": ["meet"],
        "meet": ["meat"],
        "sweet": ["suite"],
        "suite": ["sweet"],
        "great": ["grate"],
        "grate": ["great"],
        "wheat": ["weet"],
        "pair": ["pear", "pare"],
        "pear": ["pair", "pare"],
    }

    # Food-domain STT misrecognitions
    STT_FOOD_CONFUSIONS: dict[str, list[str]] = {
        "lox": ["locks", "locs"],
        "sesame": ["says me", "says a me"],
        "bagel": ["beagle", "bail"],
        "pumpernickel": ["pump nickel", "pumper nickel"],
        "espresso": ["expresso"],
        "croissant": ["crescent", "kwason"],
        "focaccia": ["four gotcha", "fo catch a"],
        "brioche": ["brie osh", "breeyosh"],
        "prosciutto": ["pro shoot oh", "proshuto"],
        "sriracha": ["sir racha", "shiracha"],
        "acai": ["ah sigh", "a kai"],
        "quinoa": ["keen wah", "kinoa"],
        "jalapeno": ["holla peen yo", "jalapino"],
        "chipotle": ["chipoltay", "chipolte"],
        "matcha": ["match a", "motcha"],
        "turmeric": ["tumeric", "ter meric"],
        "caramel": ["carmel"],
        "mozzarella": ["motzerella", "mots a rella"],
    }

    # Word boundary errors (splits and merges)
    STT_BOUNDARY_ERRORS: dict[str, str] = {
        "cream cheese": "cream she's",
        "iced tea": "ice tea",
        "ice cream": "I scream",
        "everything": "every thing",
        "without": "with out",
        "scrambled": "scram bold",
        "omelette": "om let",
        "avocado": "have a cado",
        "a lot": "alot",
        "all right": "alright",
    }

    # Contraction misrecognitions
    STT_CONTRACTION_ERRORS: dict[str, list[str]] = {
        "i'll": ["isle", "aisle", "i will"],
        "don't": ["donut", "dome"],
        "can't": ["cant", "can"],
        "won't": ["want", "wont"],
        "i'd": ["id", "eyed"],
        "i've": ["iv", "i of"],
        "let's": ["lets", "less"],
        "that's": ["thats", "that is"],
    }

    # Synonyms for common ordering words
    ORDERING_SYNONYMS: dict[str, list[str]] = {
        "get": ["have", "order", "take", "grab", "want"],
        "i'll have": ["i want", "i'd like", "can i get", "give me", "let me get"],
        "i'll take": ["i want", "i'd like", "can i get", "give me"],
        "without": ["no", "hold the", "skip the", "minus", "leave off the"],
        "with": ["add", "plus", "including", "and"],
        "please": ["", "pls", "plz"],
        "and": ["also", "plus", "&", "as well as"],
        "a": ["one", "1", ""],
        "two": ["2", "a couple", "a pair of"],
        "three": ["3"],
        "large": ["lg", "big"],
        "medium": ["med", "regular"],
        "small": ["sm", "little"],
        "iced": ["ice", "cold"],
        "hot": ["warm", "heated"],
    }

    # Common abbreviations
    ABBREVIATIONS: dict[str, str] = {
        "cream cheese": "cc",
        "orange juice": "oj",
        "bacon egg and cheese": "bec",
        "bacon egg cheese": "bec",
        "peanut butter": "pb",
        "everything": "evr",
        "toasted": "tst",
    }

    # Filler words to insert
    FILLER_WORDS: list[str] = [
        "um",
        "uh",
        "like",
        "just",
        "actually",
        "basically",
        "so",
        "well",
        "hmm",
        "oh",
    ]

    # Polite phrases to add at start or end
    POLITE_PHRASES_START: list[str] = [
        "hi",
        "hello",
        "hey",
        "hi there",
        "excuse me",
    ]

    POLITE_PHRASES_END: list[str] = [
        "please",
        "thanks",
        "thank you",
        "please and thank you",
        "if you don't mind",
    ]

    def __init__(self, seed: int | None = None) -> None:
        """Initialize the mutator with optional random seed."""
        self.rng = random.Random(seed)

    def mutate(
        self, text: str, mutation_count: int = 1, gentle: bool = False,
        stt: bool = False,
    ) -> MutationResult:
        """Apply random mutations to the text.

        Args:
            text: The original text to mutate.
            mutation_count: Number of mutations to attempt.
            gentle: If True, only use safe mutations (no typos, no word doubling).
            stt: If True, use STT-specific mutation pool instead of text mutations.

        Returns:
            MutationResult with original and mutated text.
        """
        mutated = text
        mutations_applied = []

        if stt:
            # STT mode: speech-to-text specific mutations
            mutation_methods = [
                self._apply_homophone,
                self._apply_food_confusion,
                self._apply_word_boundary_error,
                self._apply_contraction_error,
                self._apply_word_truncation,
                self._apply_stuttering,
                self._drop_connector,
            ]
        elif gentle:
            # Gentle mode: only safe mutations that don't touch item names
            mutation_methods = [
                self._add_filler_word,
                self._add_polite_phrase,
            ]
        else:
            # Full mode: all mutations including typos
            mutation_methods = [
                self._apply_typo,
                self._apply_synonym,
                self._apply_word_order_swap,
                self._add_filler_word,
                self._apply_abbreviation,
                self._apply_case_change,
                self._remove_article,
                self._double_word,
            ]

        for _ in range(mutation_count):
            method = self.rng.choice(mutation_methods)
            result = method(mutated)
            if result != mutated:
                mutated = result
                mutations_applied.append(method.__name__)

        return MutationResult(
            original=text,
            mutated=mutated,
            mutations_applied=mutations_applied,
        )

    def _apply_typo(self, text: str) -> str:
        """Apply a random typo to the text."""
        words = text.split()
        if not words:
            return text

        # Choose a random word to modify (prefer longer words)
        candidates = [i for i, w in enumerate(words) if len(w) >= 4]
        if not candidates:
            candidates = list(range(len(words)))

        idx = self.rng.choice(candidates)
        word = words[idx]

        typo_type = self.rng.choice(["transpose", "missing", "double", "adjacent"])

        if typo_type == "transpose" and len(word) >= 2:
            # Transpose two adjacent letters
            pos = self.rng.randint(0, len(word) - 2)
            word = word[:pos] + word[pos + 1] + word[pos] + word[pos + 2:]
        elif typo_type == "missing" and len(word) >= 3:
            # Remove a letter (not first or last)
            pos = self.rng.randint(1, len(word) - 2)
            word = word[:pos] + word[pos + 1:]
        elif typo_type == "double" and len(word) >= 2:
            # Double a letter
            pos = self.rng.randint(0, len(word) - 1)
            word = word[:pos] + word[pos] + word[pos:]
        elif typo_type == "adjacent":
            # Replace with adjacent keyboard letter
            keyboard_adjacent = {
                "a": "sqw", "s": "adwez", "d": "sfecr", "f": "dgrtv",
                "g": "fhtyb", "h": "gjyun", "j": "hkuim", "k": "jloip",
                "l": "kop", "q": "wa", "w": "qase", "e": "wsdr",
                "r": "edft", "t": "rfgy", "y": "tghu", "u": "yhjik",
                "i": "ujko", "o": "iklp", "p": "ol", "z": "xas",
                "x": "zscda", "c": "xdfv", "v": "cfgb", "b": "vghn",
                "n": "bhjm", "m": "njk",
            }
            for i, char in enumerate(word.lower()):
                if char in keyboard_adjacent:
                    replacement = self.rng.choice(keyboard_adjacent[char])
                    if word[i].isupper():
                        replacement = replacement.upper()
                    word = word[:i] + replacement + word[i + 1:]
                    break

        words[idx] = word
        return " ".join(words)

    def _apply_synonym(self, text: str) -> str:
        """Replace a word or phrase with a synonym."""
        text_lower = text.lower()

        # Try phrase synonyms first (longer matches)
        for phrase, synonyms in sorted(
            self.ORDERING_SYNONYMS.items(), key=lambda x: -len(x[0])
        ):
            if phrase in text_lower:
                synonym = self.rng.choice(synonyms)
                # Find the phrase case-insensitively and replace
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                return pattern.sub(synonym, text, count=1)

        return text

    def _apply_word_order_swap(self, text: str) -> str:
        """Swap word order in certain patterns."""
        # Pattern: "adjective noun" -> "noun adjective"
        # e.g., "toasted bagel" -> "bagel toasted"
        words = text.split()
        if len(words) < 2:
            return text

        # Find adjective-noun pairs to potentially swap
        adjectives = {"toasted", "plain", "large", "small", "medium", "iced", "hot"}

        for i in range(len(words) - 1):
            if words[i].lower() in adjectives:
                # Swap adjacent words
                words[i], words[i + 1] = words[i + 1], words[i]
                return " ".join(words)

        return text

    def _add_filler_word(self, text: str) -> str:
        """Add a filler word to the text."""
        filler = self.rng.choice(self.FILLER_WORDS)
        words = text.split()

        if not words:
            return text

        # Insert at beginning, middle, or after first few words
        position = self.rng.choice(["start", "early", "middle"])

        if position == "start":
            return f"{filler} {text}"
        elif position == "early" and len(words) >= 2:
            insert_pos = self.rng.randint(1, min(3, len(words)))
            words.insert(insert_pos, filler)
            return " ".join(words)
        else:
            insert_pos = self.rng.randint(0, len(words))
            words.insert(insert_pos, filler)
            return " ".join(words)

    def _add_polite_phrase(self, text: str) -> str:
        """Add a polite phrase at the start or end."""
        position = self.rng.choice(["start", "end"])

        if position == "start":
            phrase = self.rng.choice(self.POLITE_PHRASES_START)
            # Add comma or just space
            separator = self.rng.choice([", ", " "])
            return f"{phrase}{separator}{text}"
        else:
            phrase = self.rng.choice(self.POLITE_PHRASES_END)
            return f"{text} {phrase}"

    def _apply_abbreviation(self, text: str) -> str:
        """Replace common phrases with abbreviations."""
        text_lower = text.lower()

        for phrase, abbrev in self.ABBREVIATIONS.items():
            if phrase in text_lower:
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                return pattern.sub(abbrev, text, count=1)

        return text

    def _apply_case_change(self, text: str) -> str:
        """Apply random case changes."""
        case_type = self.rng.choice(["lower", "upper", "title", "random"])

        if case_type == "lower":
            return text.lower()
        elif case_type == "upper":
            return text.upper()
        elif case_type == "title":
            return text.title()
        else:
            # Random case for each character
            return "".join(
                c.upper() if self.rng.random() > 0.5 else c.lower() for c in text
            )

    def _remove_article(self, text: str) -> str:
        """Remove articles (a, an, the) from the text."""
        # Remove articles but keep spacing clean
        result = re.sub(r"\b(a|an|the)\s+", "", text, flags=re.IGNORECASE)
        return result.strip()

    def _double_word(self, text: str) -> str:
        """Accidentally double a word (common typo)."""
        words = text.split()
        if len(words) < 2:
            return text

        idx = self.rng.randint(0, len(words) - 1)
        words.insert(idx + 1, words[idx])
        return " ".join(words)

    # --- STT (Speech-to-Text) mutation methods ---

    def _apply_homophone(self, text: str) -> str:
        """Swap a word with its homophone."""
        words = text.split()
        if not words:
            return text

        # Find words that have homophones
        candidates = [
            (i, w) for i, w in enumerate(words)
            if w.lower() in self.STT_HOMOPHONES
        ]
        if not candidates:
            return text

        idx, word = self.rng.choice(candidates)
        replacement = self.rng.choice(self.STT_HOMOPHONES[word.lower()])
        # Preserve capitalization of first char
        if word[0].isupper():
            replacement = replacement.capitalize()
        words[idx] = replacement
        return " ".join(words)

    def _apply_food_confusion(self, text: str) -> str:
        """Replace a food term with an STT misrecognition."""
        text_lower = text.lower()

        # Try each food confusion (longest match first)
        for food, confusions in sorted(
            self.STT_FOOD_CONFUSIONS.items(), key=lambda x: -len(x[0])
        ):
            if food in text_lower:
                replacement = self.rng.choice(confusions)
                pattern = re.compile(re.escape(food), re.IGNORECASE)
                return pattern.sub(replacement, text, count=1)

        return text

    def _apply_word_boundary_error(self, text: str) -> str:
        """Merge or split word boundaries."""
        text_lower = text.lower()

        for phrase, replacement in self.STT_BOUNDARY_ERRORS.items():
            if phrase in text_lower:
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                return pattern.sub(replacement, text, count=1)

        return text

    def _apply_contraction_error(self, text: str) -> str:
        """Mangle contractions."""
        text_lower = text.lower()

        for contraction, replacements in self.STT_CONTRACTION_ERRORS.items():
            if contraction in text_lower:
                replacement = self.rng.choice(replacements)
                pattern = re.compile(re.escape(contraction), re.IGNORECASE)
                return pattern.sub(replacement, text, count=1)

        return text

    def _apply_word_truncation(self, text: str) -> str:
        """Cut the ending off a long word (7+ chars), simulating STT cutoff."""
        words = text.split()
        if not words:
            return text

        candidates = [i for i, w in enumerate(words) if len(w) >= 7]
        if not candidates:
            return text

        idx = self.rng.choice(candidates)
        word = words[idx]
        # Cut off 2-3 chars from the end
        cut = self.rng.randint(2, min(3, len(word) - 4))
        words[idx] = word[:-cut]
        return " ".join(words)

    def _apply_stuttering(self, text: str) -> str:
        """Repeat 1-3 words, simulating natural speech disfluency."""
        words = text.split()
        if not words:
            return text

        # Pick a starting position and repeat count
        start = self.rng.randint(0, len(words) - 1)
        repeat_count = self.rng.randint(1, min(3, len(words) - start))
        repeated = words[start:start + repeat_count]

        # Insert the repeated words right after the original
        result = words[:start + repeat_count] + repeated + words[start + repeat_count:]
        return " ".join(result)

    def _drop_connector(self, text: str) -> str:
        """Drop a connector word (a, an, the, and, with)."""
        connectors = {"a", "an", "the", "and", "with"}
        words = text.split()
        if not words:
            return text

        candidates = [i for i, w in enumerate(words) if w.lower() in connectors]
        if not candidates:
            return text

        idx = self.rng.choice(candidates)
        words.pop(idx)
        return " ".join(words)
