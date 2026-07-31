"""Tests for mimic_transform.py — pure text transformation functions.

Covers:
  - Consonant replacements (р→й, ш→с, щ→с, ж→з, ч→ц)
  - Conditional vowel replacements (у→ю, ы→и only after consonants)
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
        assert mimic_transform("мама мыла раму широкой щеткой") == "мама мила йамю сийокой сеткой"

    def test_druzhishche(self):
        assert mimic_transform("как дела дружище") == "как дела дйюзисе"

    def test_zhuk_zhuzhzhit(self):
        assert mimic_transform("черный жук жужжит") == "цейний зюк зюззит"

    def test_ryba_uplyla(self):
        """Р→Й (case!), initial у unchanged, ы→и after л."""
        assert mimic_transform("Рыба уплыла в реку") == "Йиба уплила в йекю"

    def test_all_caps(self):
        assert mimic_transform("ЩУКА и ЖАБА") == "СЮКА и ЗАБА"

    def test_initial_u_unchanged(self):
        assert mimic_transform("У Ивана усы") == "У Ивана уси"

    def test_mysh(self):
        """ь is not a consonant — vowel not changed after it."""
        assert mimic_transform("мышь бежит мыши") == "мись безит миси"


# ═══════════════════════════════════════════════════════════════════
# B. Individual consonant rules
# ═══════════════════════════════════════════════════════════════════

class TestConsonantReplacements:
    """Each consonant replacement rule tested individually."""

    def test_r_to_y_lower(self):
        assert mimic_transform("рука") == "йюка"

    def test_r_to_y_upper(self):
        assert mimic_transform("Рука") == "Йюка"

    def test_sh_to_s_lower(self):
        assert mimic_transform("шапка") == "сапка"

    def test_sh_to_s_upper(self):
        assert mimic_transform("ШАПКА") == "САПКА"

    def test_shch_to_s_lower(self):
        assert mimic_transform("щенок") == "сенок"

    def test_shch_to_s_upper(self):
        assert mimic_transform("ЩЕНОК") == "СЕНОК"

    def test_zh_to_z_lower(self):
        assert mimic_transform("жаба") == "заба"

    def test_zh_to_z_upper(self):
        assert mimic_transform("ЖАБА") == "ЗАБА"

    def test_ch_to_ts_lower(self):
        assert mimic_transform("чай") == "цай"

    def test_ch_to_ts_upper(self):
        assert mimic_transform("ЧАЙ") == "ЦАЙ"


# ═══════════════════════════════════════════════════════════════════
# C. Conditional vowel rules
# ═══════════════════════════════════════════════════════════════════

class TestVowelReplacements:
    """Vowel replacements ONLY after Cyrillic consonants."""

    def test_u_after_consonant(self):
        assert mimic_transform("тут") == "тют"

    def test_y_after_consonant(self):
        assert mimic_transform("мыло") == "мило"

    def test_u_at_start_unchanged(self):
        """у at the very start of string is NOT after a consonant."""
        assert mimic_transform("утка") == "утка"

    def test_u_after_space_unchanged(self):
        """у after space (not a consonant) — unchanged."""
        assert mimic_transform("я ушел") == "я усел"
        # "я" not in any map → unchanged
        # " " unchanged
        # "у" at i=2, text[1]=' ' (space not in CYRILLIC_CONSONANTS) → unchanged
        # "ш"→"с", "е" unchanged, "л" unchanged
        # Result: "я усел" — у unchanged ✓

    def test_y_after_vowel_unchanged(self):
        """ы after a vowel — unchanged (а is not a consonant)."""
        assert mimic_transform("паык") == "паык"

    def test_u_after_vowel_unchanged(self):
        """у after a vowel — unchanged (а is not a consonant)."""
        assert mimic_transform("паук") == "паук"

    def test_u_after_original_consonant_that_gets_replaced(self):
        """у after ш (which becomes с) — both ш and с are consonants."""
        assert "ю" in mimic_transform("шуба")  # ш→с, у→ю after ш(consonant) → "сюба"

    def test_y_after_replaced_consonant(self):
        """ы after ж (which becomes з) — both are consonants."""
        assert "и" in mimic_transform("жыр")  # ж→з, ы→и after ж(consonant) → "зий"


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
        assert mimic_transform("hello привет world") == "hello пйивет world"
        # п unchanged, р→й, и unchanged, в unchanged, е unchanged, т unchanged
        # Result: "hello пйивет world"
        # Wait: "привет" → п→п, р→й, и→и, в→в, е→е, т→т → "пйивет" ✓

    def test_punctuation_preserved(self):
        assert mimic_transform("«привет!»") == "«пйивет!»"

    def test_digits_preserved(self):
        assert mimic_transform("123 рыба 456") == "123 йиба 456"

    def test_emoji_preserved(self):
        assert mimic_transform("привет 👋 рыба 🐟") == "пйивет 👋 йиба 🐟"

    def test_multiple_spaces_preserved(self):
        assert mimic_transform("мама   мыла") == "мама   мила"

    def test_newline_preserved(self):
        assert mimic_transform("мама\nмыла") == "мама\nмила"


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
        # Р→Й (upper), ы→и after Р (upper stays? No, ы is lower, и is lower), Б unchanged, а unchanged
        assert result == "ЙиБа"

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
