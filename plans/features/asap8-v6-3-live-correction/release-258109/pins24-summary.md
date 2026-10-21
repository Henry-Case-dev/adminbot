# REL-258109 pins24 - probeg 24 py pin-files

**868 passed / 0 failed, EXIT 0** - paritet s pretcedentami 101-108.

Komanda: `.venv/Scripts/python.exe -m pytest <24 py pin-fajla> -q -p no:cacheprovider`
(polnyj log - `pins24-full.txt`).

Interpretator - strogo venv (trebovanie requirements.txt aiogram>=3.31.0); global'nyj `py -3`
(aiogram 3.29.1, `InputRichMessage.model_fields` bez `media`) dayot obruchennyj krasnyj
1f/867p na rich-publish teste - izvestnyj env-artefakt, diagnostika v README REL-258108.
