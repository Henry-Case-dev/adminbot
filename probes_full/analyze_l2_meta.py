#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Детектор мета-вступлений L2 (P0-CORRECTIVE §3, разбор замечания F2).

Зачем: `analysis.json` прошлого прогона считал `meta=[]` для ответа
«Ох бля… Ладно, глянул твои сообщения…», потому что старый regex требовал
совпадения с САМОГО НАЧАЛА строки. Преамбула во втором предложении давала
ложный зелёный. Этот детектор смотрит первые 1–2 предложения первого абзаца
(и первую строку на ярлыки) и разделяет три РАЗНЫЕ категории:

* ``announce`` — анонс действия: «сейчас разложу», «давай разберём»,
  «глянул твои сообщения», «начнём с»;
* ``leadin`` — служебная подводка: «ладно», «ок», «да без проблем»,
  «смотри», «итак» — до первого содержательного предложения;
* ``label`` — отчётный ярлык: «**Вердикт:**», «Итог:», «# Разбор».

Категории не исключают друг друга («Ладно, глянул…» — подводка + анонс),
но в отчёте они раздельны, чтобы правка промпта адресовалась точечно.

Что НЕ мета: эмоциональная реакция на запрос («Ох бля, Макс, ну ты даёшь
запрос», «Бля, ты серьёзно?»), прямое обращение и цитаты пользователя —
цитаты вырезаются до сопоставления. Ответ без всех трёх категорий = чистый.

Режимы:
    py -3 probes_full/analyze_l2_meta.py --raw <raw.json> [...] [--json]
    py -3 probes_full/analyze_l2_meta.py --self-check

``--self-check`` — контроли на УЖЕ закоммиченных raw: негативный (5 из 8
преамбул прошлого прогона обязаны быть найдены ровно этими и никакими
другими) и положительный (чистые ответы того же прогона + эталонные чистые
строки не должны давать ни одной категории). Без сети, без LLM.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

#: Порядок и имена категорий отчёта (правка промпта адресуется по имени).
CATEGORIES = ("announce", "leadin", "label")

#: Сколько первых предложений первого абзаца считается «вступлением».
WINDOW_SENTENCES = 2

#: Пользовательские цитаты: их содержимое — не речь бота.
_QUOTE_RE = re.compile(
    r"«[^»]{0,400}»|“[^”]{0,400}”|\"[^\"\n]{0,400}\"|„[^“”]{0,400}[“”]")

#: Границы предложений. Многоточие и «!?» — тоже границы.
_SENT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")

#: Анонс действия: глагол действия в связке с намерением/отчётом о шаге.
_ANNOUNCE_PATTERNS = (
    # «сейчас разложу», «ща посмотрю», «давай разберём», «давайте глянем»
    r"(?i)\b(?:сейчас|щас|ща|давай(?:те)?|тут же|сразу|для начала|первым делом)\b"
    r"[^.!?\n]{0,40}?\b(?:разлож\w*|разбер\w*|посмотр\w*|глян\w*|покаж\w*|"
    r"расскаж\w*|провер\w*|проанализиру\w*|опиш\w*|объясн\w*|сравн\w*|"
    r"собер\w*|посчита\w*|начн\w*|приступ\w*|пройд\w*сь|пробег\w*сь|"
    r"выпиш\w*|перечисл\w*)\b",
    # «глянул твои сообщения», «посмотрел переписку», «проверил историю»
    r"(?i)\b(?:уже\s+)?(?:глян\w*|посмотр\w*|провер\w*|прочита\w*|"
    r"пробеж\w*ся|прош\w*ся|перечита\w*)\b[^.!?\n]{0,30}?\b(?:сообщени\w*|"
    r"переписк\w*|истори\w*|чат\w*|тво\w*|твой\w*|диалог\w*|кусок\w*|"
    r"контекст\w*)\b",
    # «начну с», «начнём с», «разбор такой», «разбираю по пунктам»
    r"(?i)\b(?:начн\w*|начал\w*)\s+(?:с|со)\b",
    r"(?i)\b(?:разбор|разбираю|разложу|раскладываю)\b[^.!?\n]{0,20}?"
    r"\b(?:по пунктам|по порядку|по полочкам|такой|следующий)\b",
)

#: Служебная подводка: заполнитель/согласие до содержания.
_LEADIN_PATTERNS = (
    r"(?i)^(?:ну\s+|ой\s+|ах\s+|эх\s+|так\s+|и\s+)?(?:ладно|окей|ок|"
    r"хорошо|ага|угу|итак|значит|смотри|слушай|погоди|погодь|стоп)\b"
    r"[^.!?\n]{0,50}[,.!?…]",
    r"(?i)^(?:да\s+)?без\s+проблем\b[^.!?\n]{0,60}[,.!?…]",
    r"(?i)^(?:ну\s+)?(?:давай|давайте)\b(?![^.!?\n]{0,20}\b(?:ты|вы)\b)"
    r"[^.!?\n]{0,40}[,.!?…]",
    r"(?i)^(?:конечно|само собой|разумеется|да, конечно)\b"
    r"[^.!?\n]{0,40}[,.!?…]",
    r"(?i)^(?:сейчас|щас|ща)\b[^.!?\n]{0,40}[,.!?…]",
    r"(?i)^(?:и\s+)?(?:вот|вот\s+только|другое дело)\b[^.!?\n]{0,40}[,.!?…]",
    r"(?i)^(?:так\s+вот|так\s+что|короче|в\s+общем|в\s+целом)\b"
    r"[^.!?\n]{0,40}[,.!?…]",
)

#: Отчётный ярлык: «**Вердикт:**», «Итог:», «# Разбор», «Резюме —».
_LABEL_KEYWORDS = (
    r"вердикт|итог|итоги|вывод|выводы|резюме|ответ|разбор|анализ|кратко|"
    r"короче|сумма|суммируя|главное|что\s+в\s+итоге|заключение|"
    r"результат|оценка"
)
_LABEL_PATTERNS = (
    r"(?im)^[ \t]*(?:\*\*|__)?(?:%s)(?:\*\*|__)?[ \t]*[:：\-—–]" % _LABEL_KEYWORDS,
    r"(?im)^[ \t]*#{1,6}[ \t]+\S",
    r"(?im)^[ \t]*(?:%s)[ \t]*$" % _LABEL_KEYWORDS,
)

_ANNOUNCE_RE = [re.compile(p) for p in _ANNOUNCE_PATTERNS]
_LEADIN_RE = [re.compile(p) for p in _LEADIN_PATTERNS]
_LABEL_RE = [re.compile(p) for p in _LABEL_PATTERNS]


def _strip_quotes(text: str) -> str:
    """Убрать пользовательские цитаты, сохранив смещения (замена на пробелы)."""
    return _QUOTE_RE.sub(lambda m: " " * len(m.group(0)), text)


def intro_window(text: str) -> str:
    """Первый содержательный абзац, обрезанный до WINDOW_SENTENCES фраз.

    Пустые строки в начале не считаются абзацем; если первый абзац — одна
    короткая строка-ярлык, окно продолжается следующим непустым блоком, иначе
    ярлык «**Вердикт:**» съел бы весь бюджет окна.
    """
    clean = str(text or "").strip()
    if not clean:
        return ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", clean) if b.strip()]
    if not blocks:
        return ""
    first = blocks[0]
    if len(first) < 80 and len(blocks) > 1 and _LABEL_RE_any(first):
        first = first + "\n\n" + blocks[1]
    parts = [p for p in _SENT_RE.split(first) if p.strip()]
    return "\n".join(parts[:WINDOW_SENTENCES])


def _LABEL_RE_any(text: str) -> bool:
    return any(rx.search(text) for rx in _LABEL_RE)


def _hits(patterns, sentences) -> list[str]:
    """Срабатывания по категории: возвращаются сами предложения-носители.

    Сниппет берётся по предложению, а не по фрагменту regex: в отчёте и в
    evidence нужна фраза, которую человек прочитает, а не обрезанный кусок
    («глянул твои»). Дедупликация — по тексту предложения.
    """
    found: list[str] = []
    for sentence in sentences:
        if not sentence.strip():
            continue
        if not any(rx.search(sentence) for rx in patterns):
            continue
        snippet = re.sub(r"\s+", " ", sentence).strip()[:160]
        if snippet and snippet not in found:
            found.append(snippet)
    return found


def _label_hits(text: str) -> list[str]:
    """Ярлыки: по строке, где стоит совпадение (первый блок ответа)."""
    found: list[str] = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        if not any(rx.search(line) for rx in _LABEL_RE):
            continue
        snippet = re.sub(r"\s+", " ", line).strip()[:160]
        if snippet and snippet not in found:
            found.append(snippet)
    return found


def analyze_text(text: str) -> dict:
    """Разбор одного ответа. Никогда не бросает.

    Возвращает ``window`` (что именно считалось вступлением), найденные
    предложения по каждой категории, объединённый ``meta`` (как в прежнем
    analysis.json, но с префиксом категории) и ``flagged``.
    """
    raw = str(text or "")
    window_src = intro_window(raw)
    # Цитаты пользователя вырезаются ДО сопоставления, но не меняют разбивку
    # предложений (замена той же длины пробелами).
    sentences = [s for s in _SENT_RE.split(_strip_quotes(window_src)) if s.strip()]
    head_block = ""
    for block in re.split(r"\n\s*\n", raw.strip()):
        if block.strip():
            head_block = block.strip()
            break
    result = {
        "window": re.sub(r"\s+", " ", window_src).strip()[:400],
        "sentences": [s for s in _SENT_RE.split(window_src) if s.strip()][
            :WINDOW_SENTENCES],
        "announce": _hits(_ANNOUNCE_RE, sentences),
        "leadin": _hits(_LEADIN_RE, sentences),
        "label": _label_hits(_strip_quotes(head_block)),
    }
    meta: list[str] = []
    for name in CATEGORIES:
        meta.extend("%s: %s" % (name, hit) for hit in result[name])
    result["meta"] = meta
    result["flagged"] = bool(meta)
    return result


def analyze_raw(path: str) -> dict:
    """Разбор raw-файла прогона: каждый текст ``l2_texts`` по отдельности."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    texts = data.get("l2_texts")
    if texts is None:
        texts = [r.get("answer") or r.get("text") or ""
                 for r in (data.get("l2_runs") or [])]
    rows = []
    for idx, text in enumerate(texts or []):
        rep = analyze_text(text)
        rep["index"] = idx
        rep["chars"] = len(str(text or ""))
        rows.append(rep)
    return {"path": path, "label": data.get("label", ""),
            "case": data.get("case", ""), "rows": rows,
            "flagged": sum(1 for r in rows if r["flagged"]),
            "total": len(rows)}


EVIDENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plans", "features", "asap-speech-arch", "evidence", "p0-hotfix",
    "probes_final2")

#: Негативный контроль: ответы прогона 0428c271 (до правки c0d5a3d3).
#: Ожидание — ровно эти (файл, индекс); «лишнее» срабатывание тоже провал.
NEGATIVE_CONTROL = {
    "raw_new_code_A.json": (0,),
    "raw_new_code_B.json": (1,),
    "raw_new_forced_A.json": (0,),
    "raw_new_forced_B.json": (0, 1),
}

#: Положительный контроль: чистые эталоны (без вступлений и ярлыков).
POSITIVE_SAMPLES = (
    "Ты не злобный, ты просто устал спорить с ветряными мельницами.",
    "Бля, Макс, ты серьёзно? Я ж тебе уже ответил — досье я не собираю.",
    "Костя рофлит, а не троллит: он кидает ссылки и сам же над ними "
    "смеётся.\n\nДальше по теме — Ринтаро действительно цепляется к мелочам.",
    "Он не злой, он нудный. Разница в том, что злой хочет задеть, а нудный — "
    "просто не чувствует момента.",
)


def self_check(json_out: bool = False) -> int:
    results: dict[str, bool] = {}
    detail: dict[str, object] = {}

    # 1) положительный контроль: эталонные чистые строки — 0 категорий
    pos_bad = []
    for sample in POSITIVE_SAMPLES:
        rep = analyze_text(sample)
        if rep["flagged"]:
            pos_bad.append({"text": sample[:60], "meta": rep["meta"]})
    results["positive_clean_samples"] = not pos_bad
    detail["positive_bad"] = pos_bad

    # 2) негативный контроль: 5 из 8 преамбул прошлого прогона, ровно эти
    per_file: dict[str, list] = {}
    missed, extra = [], []
    results["negative_raw_present"] = True
    for name, expected in NEGATIVE_CONTROL.items():
        path = os.path.join(EVIDENCE_DIR, name)
        if not os.path.exists(path):
            results["negative_raw_present"] = False
            detail["missing_raw"] = path
            break
        rep = analyze_raw(path)
        per_file[name] = [{"index": r["index"], "meta": r["meta"]}
                          for r in rep["rows"] if r["flagged"]]
        got = tuple(r["index"] for r in rep["rows"] if r["flagged"])
        if got != expected:
            for idx in expected:
                if idx not in got:
                    missed.append("%s#%d" % (name, idx))
            for idx in got:
                if idx not in expected:
                    extra.append("%s#%d" % (name, idx))
    else:
        results["negative_raw_present"] = True
    if "negative_raw_present" in results and results["negative_raw_present"]:
        results["negative_known_five"] = not missed and not extra
    detail["negative"] = per_file
    detail["negative_missed"] = missed
    detail["negative_extra"] = extra

    # 3) детектор ловит каждый тип по отдельности (ярлык и подводка отдельно)
    cases = {
        "announce": "Сейчас разложу по пунктам: первое — он не злой.",
        "leadin": "Ладно, ты заступился за Костю, и это нормально.",
        "label": "**Вердикт:** он не злобный, просто устал.",
        "clean": "Он не злобный, просто устал от споров.",
    }
    per_type = {}
    for name, sample in cases.items():
        rep = analyze_text(sample)
        hit = [c for c in CATEGORIES if rep[c]]
        per_type[name] = hit
        if name == "clean":
            ok = not hit
        else:
            ok = bool(hit) and all(c in CATEGORIES for c in hit)
        results["type_%s" % name] = ok
    detail["per_type"] = per_type

    ok = all(results.values())
    out = {"self_check": "PASS" if ok else "FAIL", "results": results,
           "detail": detail, "window_sentences": WINDOW_SENTENCES}
    if json_out:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", nargs="*", default=[],
                    help="raw-файлы прогона (json с l2_texts)")
    ap.add_argument("--glob", default="",
                    help="маска raw-файлов, например "
                         "'.../probes_final2/raw_new_*.json'")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        return self_check(json_out=args.json)
    paths = list(args.raw)
    if args.glob:
        paths.extend(sorted(glob.glob(args.glob)))
    if not paths:
        print("нужен --raw/--glob или --self-check", file=sys.stderr)
        return 2
    reports = [analyze_raw(p) for p in paths]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=1))
        return 0
    total = sum(r["total"] for r in reports)
    flagged = sum(r["flagged"] for r in reports)
    for rep in reports:
        print("%s case=%s flagged=%d/%d" % (os.path.basename(rep["path"]),
                                            rep["case"] or "-", rep["flagged"],
                                            rep["total"]))
        for row in rep["rows"]:
            mark = "META" if row["flagged"] else "ok  "
            print("  %s #%d %s" % (mark, row["index"], row["window"][:140]))
            for item in row["meta"]:
                print("        - %s" % item)
    print("TOTAL %d/%d" % (flagged, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
