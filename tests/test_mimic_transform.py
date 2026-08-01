"""Tests for mimic_transform.py — pure text transformation functions.

Covers:
  - WORD_MAP and SUBSTR_MAP replacements (whole-word and substring)
  - Consonant replacements (р→л, ш→ф, щ→ф, ж→з, ч→т)
  - Conditional vowel replacements (у→ю only after consonants)
  - Case preservation (upper/lower/title)
  - Non-Cyrillic passthrough (punctuation, digits, Latin, emoji)
  - Edge cases (empty string, word boundaries, consonant chain)
  - count_words
  - Property-based invariants (length preservation, idempotence)
"""
import pytest
from services.mimic_transform import mimic_transform, count_words


# ═══════════════════════════════════════════════════════════════════
# A. Core transformation — verified test cases from ARCHITECTURE.md
# ═══════════════════════════════════════════════════════════════════

class TestMimicTransformVerified:
    """Tests matching the verified cases in ARCHITECTURE.md §3.1.3."""

    def test_classic_case(self):
        assert mimic_transform("мама мыла раму широкой щеткой") == "мама мыла ламю филокой феткой"

    def test_druzhishche(self):
        assert mimic_transform("как дела дружище") == "как дела длюзифе"

    def test_zhuk_zhuzhzhit(self):
        assert mimic_transform("черный жук жужжит") == "телный зюк зюззит"

    def test_ryba_uplyla(self):
        """Р→Л (case!), initial у unchanged, ы unchanged (no ы→и in new algorithm)."""
        assert mimic_transform("Рыба уплыла в реку") == "Лыба уплыла в лекю"

    def test_all_caps(self):
        assert mimic_transform("ЩУКА и ЖАБА") == "ФЮКА и ЗАБА"

    def test_initial_u_unchanged(self):
        assert mimic_transform("У Ивана усы") == "У Ивана усы"

    def test_mysh(self):
        """ь is not a consonant; SUBSTR_MAP шь→ф, vowel not changed after it."""
        assert mimic_transform("мышь бежит мыши") == "мыф безит мыфи"


# ═══════════════════════════════════════════════════════════════════
# B. Individual consonant rules
# ═══════════════════════════════════════════════════════════════════

class TestConsonantReplacements:
    """Each consonant replacement rule tested individually."""

    def test_r_to_y_lower(self):
        assert mimic_transform("рука") == "люка"

    def test_r_to_y_upper(self):
        assert mimic_transform("Рука") == "Люка"

    def test_sh_to_s_lower(self):
        assert mimic_transform("шапка") == "фапка"

    def test_sh_to_s_upper(self):
        assert mimic_transform("ШАПКА") == "ФАПКА"

    def test_shch_to_s_lower(self):
        assert mimic_transform("щенок") == "фенок"

    def test_shch_to_s_upper(self):
        assert mimic_transform("ЩЕНОК") == "ФЕНОК"

    def test_zh_to_z_lower(self):
        assert mimic_transform("жаба") == "заба"

    def test_zh_to_z_upper(self):
        assert mimic_transform("ЖАБА") == "ЗАБА"

    def test_ch_to_ts_lower(self):
        assert mimic_transform("чай") == "тай"

    def test_ch_to_ts_upper(self):
        assert mimic_transform("ЧАЙ") == "ТАЙ"


# ═══════════════════════════════════════════════════════════════════
# C. Conditional vowel rules
# ═══════════════════════════════════════════════════════════════════

class TestVowelReplacements:
    """Vowel replacements ONLY after Cyrillic consonants."""

    def test_u_after_consonant(self):
        assert mimic_transform("тут") == "тют"

    def test_y_after_consonant(self):
        assert mimic_transform("мыло") == "мыло"

    def test_u_at_start_unchanged(self):
        """у at the very start of string is NOT after a consonant."""
        assert mimic_transform("утка") == "утка"

    def test_u_after_space_unchanged(self):
        """у after space (not a consonant) — unchanged."""
        assert mimic_transform("я ушел") == "я уфел"
        # "я" not in any map → unchanged
        # " " unchanged
        # "у" at i=2, text[1]=' ' (space not in CYRILLIC_CONSONANTS) → unchanged
        # "ш"→"ф", "е" unchanged, "л" unchanged
        # Result: "я уфел" — у unchanged ✓

    def test_y_after_vowel_unchanged(self):
        """ы after a vowel — unchanged (а is not a consonant)."""
        assert mimic_transform("паык") == "паык"

    def test_u_after_vowel_unchanged(self):
        """у after a vowel — unchanged (а is not a consonant)."""
        assert mimic_transform("паук") == "паук"

    def test_u_after_original_consonant_that_gets_replaced(self):
        """у after ш (which becomes с) — both ш and с are consonants."""
        assert "ю" in mimic_transform("шуба")  # ш→ф, у→ю after ш(consonant) → "фюба"

    def test_y_after_replaced_consonant(self):
        """ы after ж (which becomes з) — ы is not mapped in new algorithm, stays."""
        assert mimic_transform("жыр") == "зыл"


# ═══════════════════════════════════════════════════════════════════
# D. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary and edge case tests."""

    def test_empty_string(self):
        assert mimic_transform("") == ""

    def test_only_non_cyrillic(self):
        assert mimic_transform("hello 123 !@#") == "hello 123 !@#"

    def test_mixed_cyrillic_latin(self):
        assert mimic_transform("hello привет world") == "hello пливет world"
        # п unchanged, р→л, и unchanged, в unchanged, е unchanged, т unchanged
        # Result: "hello пливет world"

    def test_punctuation_preserved(self):
        assert mimic_transform("«привет!»") == "«пливет!»"

    def test_digits_preserved(self):
        assert mimic_transform("123 рыба 456") == "123 лыба 456"

    def test_emoji_preserved(self):
        assert mimic_transform("привет 👋 рыба 🐟") == "пливет 👋 лыба 🐟"

    def test_multiple_spaces_preserved(self):
        assert mimic_transform("мама   мыла") == "мама   мыла"

    def test_newline_preserved(self):
        assert mimic_transform("мама\nмыла") == "мама\nмыла"


# ═══════════════════════════════════════════════════════════════════
# E. Property-based invariants
# ═══════════════════════════════════════════════════════════════════

class TestInvariants:
    """Property-based invariants that must hold for ALL inputs."""

    def test_length_preserved(self):
        samples = [
            "мама мыла раму",
            "привет как дела",
            "hello world",
            "123",
            "",
            "а" * 100,
        ]
        for s in samples:
            assert len(mimic_transform(s)) == len(s), f"Length mismatch for: {s!r}"

    def test_non_cyrillic_passthrough(self):
        """Every non-Cyrillic character stays exactly the same."""
        text = "Hello, World! 123 — это тест."
        result = mimic_transform(text)
        for i, ch in enumerate(text):
            if ch not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ":
                assert result[i] == ch, f"Non-Cyrillic char at pos {i}: {ch!r} → {result[i]!r}"

    def test_no_changes_on_safe_words(self):
        """Words without target consonants/vowels should be unchanged."""
        safe = "кот дом сон"
        assert mimic_transform(safe) == safe

    def test_case_preserved_per_letter(self):
        """Each replaced letter keeps its case."""
        result = mimic_transform("РыБа")
        # Р→Л (upper), ы unchanged (no ы→и), Б unchanged, а unchanged
        assert result == "ЛыБа"

    def test_idempotent_for_unchanged(self):
        """Applying transform twice should not change result further
        if there are no more target chars."""
        text = "кот дом"
        once = mimic_transform(text)
        twice = mimic_transform(once)
        assert once == twice == text


# ═══════════════════════════════════════════════════════════════════
# F. count_words
# ═══════════════════════════════════════════════════════════════════

class TestCountWords:
    """Tests for count_words utility."""

    def test_empty(self):
        assert count_words("") == 0

    def test_single_word(self):
        assert count_words("привет") == 1

    def test_multiple_words(self):
        assert count_words("мама мыла раму") == 3

    def test_extra_spaces(self):
        assert count_words("  мама   мыла  ") == 2

    def test_newlines(self):
        assert count_words("мама\nмыла\nраму") == 3

    def test_only_spaces(self):
        assert count_words("   ") == 0
