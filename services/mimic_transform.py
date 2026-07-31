CONSONANT_MAP = {
    "р": "й", "Р": "Й",
    "ш": "с", "Ш": "С",
    "щ": "с", "Щ": "С",
    "ж": "з", "Ж": "З",
    "ч": "ц", "Ч": "Ц",
}

VOWEL_MAP_AFTER_CONSONANT = {
    "у": "ю", "У": "Ю",
    "ы": "и", "Ы": "И",
}

CYRILLIC_CONSONANTS = frozenset("бвгджзйклмнпрстфхцчшщБВГДЖЗЙКЛМНПРСТФХЦЧШЩ")


def mimic_transform(text: str) -> str:
    chars = list(text)
    result = []

    for i, ch in enumerate(chars):
        if ch in CONSONANT_MAP:
            result.append(CONSONANT_MAP[ch])
        elif ch in VOWEL_MAP_AFTER_CONSONANT and i > 0 and text[i - 1] in CYRILLIC_CONSONANTS:
            result.append(VOWEL_MAP_AFTER_CONSONANT[ch])
        else:
            result.append(ch)

    return "".join(result)


def count_words(text: str) -> int:
    if not text:
        return 0
    return len(text.split())
