"""Probe metrics: paragraphs, direct-answer position, dates/quotes, profanity."""
from __future__ import annotations

import io
import json
import re

SCRATCH = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\p0-probes"
DOC = json.load(io.open(SCRATCH + r"\raw\results.json", encoding="utf-8"))

PROFANITY = re.compile(
    r"(бля\w*|хуй\w*|ху[её]\w*|пизд\w*|еб[аеёиу]\w*|ёб\w*|жоп\w*|сук[аи]\b|"
    r"нахуй|говн\w*|мраз\w*|уёб\w*)", re.I)
DATE = re.compile(
    r"(\b(19|20)\d\d\b|\b\d{1,2}\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|"
    r"август|сентябр|октябр|ноябр|декабр)\w*|\b(январ|феврал|март|апрел|ма[йя]|"
    r"июн|июл|август|сентябр|октябр|ноябр|декабр)\w*\s+(19|20)\d\d)", re.I)
QUOTE = re.compile(r"(«[^»]{3,120}»|\"[^\"]{3,120}\")")
NUMBER = re.compile(r"\b\d{2,}\b")
HEDGE = re.compile(r"(не знаю|не помню|нет данных|недостаточно|не подтвержд|"
                   r"не могу подтвердить|неизвестн)", re.I)
HUMOR = re.compile(r"(\)\)|😄|😅|шутк|хах|лол|анекдот)", re.I)


def analyze(text: str) -> dict:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    first = paras[0] if paras else ""
    return {
        "chars": len(text),
        "paragraphs": len(paras),
        "first_para_chars": len(first),
        "first_para": first[:300],
        "dates": sorted(set(DATE.findall(text))),
        "date_tokens": sorted(set(m.group(0) for m in DATE.finditer(text))),
        "quotes": [q for q in QUOTE.findall(text)][:6],
        "numbers": sorted(set(NUMBER.findall(text)))[:12],
        "profanity": sorted(set(m.group(0).lower()
                                 for m in PROFANITY.finditer(text))),
        "hedge": sorted(set(m.group(0).lower() for m in HEDGE.finditer(text))),
        "humor_markers": sorted(set(m.group(0) for m in HUMOR.finditer(text))),
        "has_verdict": bool(re.search(
            r"(злобн\w*|агрессивн\w*|не злобн|не сказал бы|нет,\s*не)", text,
            re.I)),
    }


def main() -> None:
    rows = []
    for key, item in sorted(DOC["results"].items()):
        api = item["api"]
        metrics = analyze(api.get("text") or "") if api.get("ok") else {}
        row = {"key": key, "route": item["route"], "ok": api.get("ok"),
               "latency_s": api.get("latency_s"),
               "system_chars": item["system_chars"],
               "completion_tokens": (api.get("usage") or {}).get(
                   "completion_tokens"), **metrics}
        rows.append(row)
        print(key, json.dumps({k: v for k, v in row.items()
                               if k not in ("first_para",)},
                              ensure_ascii=False))
    io.open(SCRATCH + r"\metrics.json", "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
