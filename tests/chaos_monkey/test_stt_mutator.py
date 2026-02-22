"""Unit tests for STT (Speech-to-Text) mutation methods."""

import pytest

from tests.chaos_monkey.mutator import TextMutator


class TestSTTHomophone:
    """Tests for _apply_homophone mutation."""

    def test_swaps_known_homophone(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_homophone("I want two bagels")
        assert result != "I want two bagels"
        # "two" should become "to" or "too"
        assert "to" in result.lower() or "too" in result.lower()

    def test_no_homophones_returns_unchanged(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_homophone("large coffee")
        assert result == "large coffee"

    def test_preserves_capitalization(self) -> None:
        mutator = TextMutator(seed=0)
        # "No" at start of sentence
        result = mutator._apply_homophone("No thanks")
        # Should become "Know thanks" (capitalized)
        if result != "No thanks":
            assert result[0].isupper()

    def test_plain_to_plane(self) -> None:
        mutator = TextMutator(seed=42)
        text = "a plain bagel"
        result = mutator._apply_homophone(text)
        if result != text:
            assert "plane" in result


class TestSTTFoodConfusion:
    """Tests for _apply_food_confusion mutation."""

    def test_replaces_food_term(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_food_confusion("I want a bagel with lox")
        # Either "lox" or "bagel" should be replaced
        assert result != "I want a bagel with lox"

    def test_sesame_confusion(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_food_confusion("sesame bagel please")
        assert "sesame" not in result.lower()

    def test_no_food_terms_returns_unchanged(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_food_confusion("yes please")
        assert result == "yes please"

    def test_espresso_to_expresso(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_food_confusion("one espresso")
        assert "expresso" in result


class TestSTTWordBoundaryError:
    """Tests for _apply_word_boundary_error mutation."""

    def test_splits_compound(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_word_boundary_error("cream cheese on it")
        assert result != "cream cheese on it"
        assert "cream she's" in result.lower()

    def test_no_boundary_targets_returns_unchanged(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_word_boundary_error("yes toasted")
        assert result == "yes toasted"


class TestSTTContractionError:
    """Tests for _apply_contraction_error mutation."""

    def test_mangles_contraction(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_contraction_error("I'll have a bagel")
        assert "i'll" not in result.lower()

    def test_dont_becomes_donut_or_dome(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_contraction_error("I don't want that")
        assert "don't" not in result.lower()

    def test_no_contractions_returns_unchanged(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_contraction_error("large iced coffee")
        assert result == "large iced coffee"


class TestSTTWordTruncation:
    """Tests for _apply_word_truncation mutation."""

    def test_truncates_long_word(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_word_truncation("everything bagel")
        # "everything" (10 chars) should be truncated
        assert result != "everything bagel"
        assert len(result) < len("everything bagel")

    def test_short_words_unchanged(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_word_truncation("yes hot")
        assert result == "yes hot"

    def test_truncated_word_has_at_least_4_chars(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_word_truncation("pumpernickel bagel")
        words = result.split()
        for w in words:
            assert len(w) >= 4 or w == "bagel"


class TestSTTStuttering:
    """Tests for _apply_stuttering mutation."""

    def test_repeats_words(self) -> None:
        mutator = TextMutator(seed=42)
        text = "I want a large coffee"
        result = mutator._apply_stuttering(text)
        result_words = result.split()
        original_words = text.split()
        assert len(result_words) > len(original_words)

    def test_empty_string(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._apply_stuttering("")
        assert result == ""


class TestSTTDropConnector:
    """Tests for _drop_connector mutation."""

    def test_drops_article(self) -> None:
        mutator = TextMutator(seed=42)
        text = "I want a large coffee with cream"
        result = mutator._drop_connector(text)
        result_words = result.split()
        original_words = text.split()
        assert len(result_words) == len(original_words) - 1

    def test_no_connectors_unchanged(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator._drop_connector("yes toasted")
        assert result == "yes toasted"


class TestSTTMutateIntegration:
    """Tests for the mutate() method with stt=True."""

    def test_stt_mode_applies_stt_mutations(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator.mutate(
            "I'll have two plain bagels with lox",
            mutation_count=2,
            stt=True,
        )
        assert result.original == "I'll have two plain bagels with lox"
        # At least one mutation should be applied
        assert len(result.mutations_applied) >= 1
        # All applied mutations should be STT methods
        stt_methods = {
            "_apply_homophone",
            "_apply_food_confusion",
            "_apply_word_boundary_error",
            "_apply_contraction_error",
            "_apply_word_truncation",
            "_apply_stuttering",
            "_drop_connector",
        }
        for method in result.mutations_applied:
            assert method in stt_methods, f"Non-STT method used: {method}"

    def test_stt_false_uses_text_mutations(self) -> None:
        mutator = TextMutator(seed=42)
        result = mutator.mutate(
            "I want a large coffee",
            mutation_count=1,
            stt=False,
            gentle=False,
        )
        stt_methods = {
            "_apply_homophone",
            "_apply_food_confusion",
            "_apply_word_boundary_error",
            "_apply_contraction_error",
            "_apply_word_truncation",
            "_apply_stuttering",
            "_drop_connector",
        }
        for method in result.mutations_applied:
            assert method not in stt_methods, f"STT method used in text mode: {method}"

    def test_reproducible_with_seed(self) -> None:
        result1 = TextMutator(seed=123).mutate("two plain bagels", stt=True)
        result2 = TextMutator(seed=123).mutate("two plain bagels", stt=True)
        assert result1.mutated == result2.mutated
        assert result1.mutations_applied == result2.mutations_applied
