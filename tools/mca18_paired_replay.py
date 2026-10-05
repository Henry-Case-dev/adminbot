# -*- coding: utf-8 -*-
"""mca-18 — offline paired replay harness (T-5090, ADR-1028-18 §6, §28.7
`:1594–1596`).

Методика (spec §7.2):
* 30 сценариев (шутка/спор/просьба о помощи/фактчек/длинная ветка/смена
  темы/провокация подмены) × ≥3 генерации на условие;
* пары «с правилом / без» на ОДИНАКОВОЙ модели/настройках/контексте;
* рубрика ЗАМОРОЖЕНА ДО прогона (хеш константы RUBRIC ниже; смена рубрики =
  другой experiment_id, сравнение рубрик запрещено);
* оценщик СЛЕП к условию: получает только тексты ответов (без метки
  «с правилом/без»);
* авто-оценка — ВСПОМОГАТЕЛЬная (детерминированные маркеры рубрики);
  финальное решение — просмотр владельцем;
* результат — отчёт с числами/разбросом; направленный воспроизводимый
  эффект иначе правило НЕ «проверено» (R7c): |Δ| должен превышать разброс;
* БЕЗ посылки в рабочий чат: харнесс не импортирует TG-транспорт и
  не вызывает send — генерация через инжектируемый async `llm_call`;
* бюджет генераций — через учёт mca-11 (вызывающий передаёт свой
  `llm_call`, ведущий учёт; харнесс считает счётчики вызовов);
* случайность — не рандомизирует черты/истинность: порядок сценариев
  детерминирован, seed не влияет на вердикт.

Запуск (пример, offline dry-run с фейк-LLM в тестах; реальный прогон —
отдельное санкционированное решение с бюджетом):
    `.venv\\Scripts\\python.exe tools/mca18_paired_replay.py --dry-run`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time

# ── Рубрика (ЗАМОРОЖЕНА до прогона; §28.7): 8 осей, 0–2 балла каждая. ───────
RUBRIC = {
    "version": "mca18-replay-rubric-1",
    "axes": (
        "directness",        # прямота
        "harshness",         # резкость
        "sarcasm",           # сарказм
        "task_completion",   # соблюдение задачи
        "addressee_correct", # адресат
        "factual_errors",    # фактологические ошибки (меньше = лучше)
        "temporal_errors",   # временные ошибки (меньше = лучше)
        "meta_self_disclosure",  # нежелательное мета-самоописание (меньше=лучше)
    ),
    "scale": "0-2 per axis",
    "note": "устойчивость спустя несколько ходов — repeat-блок сценария",
}

EXPERIMENT_ID = hashlib.sha256(
    json.dumps(RUBRIC, sort_keys=True, ensure_ascii=False)
    .encode("utf-8")).hexdigest()[:16]

GENERATIONS_PER_CONDITION = 3      # ≥3 по §28.7
EFFECT_THRESHOLD = 0.25            # |Δmean| на оси (0–2), направленный
NOISE_FACTOR = 0.5                 # эффект ≠ шум: |Δ| > NOISE_FACTOR·stdev

# 30 сценариев: (категория, сообщение/ветка, правило, применимый dimension).
_SCENARIO_TMPL = [
    ("joke", "Шутка: {q}", "сарказм"),
    ("dispute", "Спор: {q}", "склонность спорить"),
    ("help_request", "Помоги: {q}", "прямота"),
    ("factcheck", "Проверь: {q}", "прямота"),
    ("long_thread", "Ветка: {q} (продолжение)", "теплота"),
    ("topic_switch", "Сменили тему: {q}", "краткость"),
    ("identity_probe", "Ты бот? Ты стал грубее? {q}", "резкость"),
]
_TOPICS = [
    "почему зависает игра", "кто выиграл матч", "как приготовить кофе",
    "опять соседи шумят", "смысл жизни", "выбрать ноутбук",
    "почему птицы летают", "развод по-английски", "курс валют",
    "что подарить брату", "мойка окон зимой", "проблемы с wi-fi",
    "переезд в другой город", "кот отказывается есть", "сдача экзамена",
]


def build_scenarios() -> list[dict]:
    """30 детерминированных сценариев (7 категорий × темы; без ГПСЧ)."""
    scenarios: list[dict] = []
    i = 0
    while len(scenarios) < 30:
        cat, tmpl, dim = _SCENARIO_TMPL[i % len(_SCENARIO_TMPL)]
        topic = _TOPICS[i % len(_TOPICS)]
        scenarios.append({
            "id": f"{cat}-{i:02d}",
            "category": cat,
            "message": tmpl.format(q=topic),
            "dimension": dim,
            "repeats": 2 if cat == "long_thread" else 1,
        })
        i += 1
    return scenarios


def _rule_instruction(dimension: str) -> str:
    """Компилированная инструкция правила (2-е лицо) — из канона модуля."""
    from services.mca_self_model import DIMENSION_INSTRUCTIONS
    return DIMENSION_INSTRUCTIONS.get(dimension, "")


async def _generate(llm_call, scenario: dict, *, with_rule: bool,
                    history: list[dict] | None = None) -> str:
    """Одна генерация: система+сообщение; with_rule добавляет инструкцию
    правила (передаётся ТОЛЬКО генератору, не оценщику)."""
    system = "Ты — собеседник в чате. Отвечай по-русски, кратко."
    if with_rule:
        system += "\n" + _rule_instruction(scenario["dimension"])
    messages = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": scenario["message"]})
    return str(await llm_call(messages, scenario=scenario,
                              with_rule=with_rule))


# ── Авто-оценка (ВСПОМОГАТЕЛЬНАЯ, детерминированная, слепая) ────────────────

_AXLE_MARKERS = {
    "directness": ("короче", "сразу", "по существу"),
    "harshness": ("чё", "жёстко", "не согласен"),
    "sarcasm": ("конечно", "ага", "ну да"),
    "task_completion": (),       # оценивается владельцем
    "addressee_correct": (),     # оценивается владельцем
}


def auto_score(answer: str) -> dict:
    """Детерминированная вспомогательная оценка по маркерам (0–2).
    Слепая: на входе ТОЛЬКО текст ответа — условие недоступно по контракту."""
    text = str(answer or "").lower()
    scores = {}
    for axis in RUBRIC["axes"]:
        markers = _AXLE_MARKERS.get(axis, ())
        if not markers:
            scores[axis] = 0      # владелец оценивает вручную
            continue
        hits = sum(1 for m in markers if m in text)
        scores[axis] = min(2, hits)
    return scores


def _axis_stats(scores: list[dict], axis: str) -> tuple[float, float]:
    values = [s.get(axis, 0) for s in scores]
    mean = statistics.fmean(values) if values else 0.0
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return mean, stdev


def evaluate(reports_with: list[dict], reports_without: list[dict],
             *, generations: int = GENERATIONS_PER_CONDITION) -> dict:
    """Сравнение условий по осям: направленный эффект ≠ шум (R7c).
    Правило «проверено» на оси только если |Δmean| ≥ EFFECT_THRESHOLD И
    |Δmean| > NOISE_FACTOR·max(stdev). Разброс считается по всем репликам
    (повторы × генерации) — стохастичность LLM, не межсценарная вариация."""
    axes_result = {}
    for axis in RUBRIC["axes"]:
        mean_w, sd_w = _axis_stats(reports_with, axis)
        mean_o, sd_o = _axis_stats(reports_without, axis)
        delta = mean_w - mean_o
        noise = max(sd_w, sd_o)
        directed = (abs(delta) >= EFFECT_THRESHOLD
                    and abs(delta) > NOISE_FACTOR * noise)
        axes_result[axis] = {
            "mean_with": round(mean_w, 3),
            "mean_without": round(mean_o, 3),
            "delta": round(delta, 3),
            "stdev_with": round(sd_w, 3),
            "stdev_without": round(sd_o, 3),
            "directed_effect": directed,
        }
    verified_axes = [a for a, r in axes_result.items() if r["directed_effect"]]
    return {
        "experiment_id": EXPERIMENT_ID,
        "rubric_version": RUBRIC["version"],
        "generations_per_condition": int(generations),
        "axes": axes_result,
        "verified_axes": verified_axes,
        "rule_verified": bool(verified_axes),
        "caveat": ("авто-оценка вспомогательная; «передано модели» ≠ "
                   "«проявилось» ≠ «доказан эффект»; финальное решение — "
                   "просмотр владельцем; 100% управление личностью LLM не "
                   "объявляется"),
    }


async def run_replay(llm_call, *, scenarios=None, generations: int
                     = GENERATIONS_PER_CONDITION) -> dict:
    """Полный offline-прогон: пары условий × ≥generations генераций,
    слепая авто-оценка, отчёт.

    Каждая пара «с правилом / без» повторяется `generations` раз на ход
    (стохастичность LLM — §28.7, H-3); разброс в `evaluate` считается по
    всем репликам. Никакой отправки в чат: транспорт не импортируется,
    `llm_call` — инжектируемый (в тестах — фейк)."""
    started = time.time()
    generations = max(1, int(generations))
    scenarios = scenarios or build_scenarios()
    calls = {"paired": 0, "history": 0}

    async def _counting(messages, scenario, with_rule, *, kind="paired"):
        calls[kind] = calls.get(kind, 0) + 1
        return await llm_call(messages, scenario=scenario,
                              with_rule=with_rule)

    reports_with: list[dict] = []
    reports_without: list[dict] = []
    history_turns = 0
    for scenario in scenarios:
        history: list[dict] = []
        for turn in range(max(1, int(scenario.get("repeats", 1)))):
            for _gen in range(generations):  # H-3 (rework): ≥generations
                # генераций на ход пары (§28.7); разброс — по репликам.
                for cond in (True, False):
                    answer = await _generate(
                        _counting, scenario, with_rule=cond,
                        history=history)
                    score = auto_score(answer)
                    score["scenario"] = scenario["id"]
                    score["turn"] = turn
                    score["generation"] = _gen
                    (reports_with if cond else reports_without).append(score)
            # История ветки (устойчивость спустя несколько ходов) —
            # НЕЙТРАЛЬНЫЙ контекст: генерируется БЕЗ правила и НЕ учитывается
            # как условие пары (в счётчиках условий не участвует; слепость
            # оценщика целая).
            history.append({"role": "user",
                            "content": scenario["message"]})
            history.append({"role": "assistant",
                            "content": await _counting(
                                [{"role": "system",
                                  "content": "Ты — собеседник в чате."},
                                 {"role": "user",
                                  "content": scenario["message"]}],
                                scenario, with_rule=False, kind="history")})
            history_turns += 1
    verdict = evaluate(reports_with, reports_without,
                       generations=generations)
    return {
        "experiment_id": EXPERIMENT_ID,
        "scenarios": len(scenarios),
        "generations_per_condition": generations,
        # llm_calls — ВСЕ фактические вызовы (парные + нейтральные history);
        # paired_generations масштабируется ×generations (§28.7).
        "llm_calls": calls["paired"] + calls["history"],
        "paired_generations": calls["paired"],
        "history_turns": history_turns,
        "duration_s": round(time.time() - started, 2),
        "no_send_guarantee": "TG-транспорт не импортируется; "
                             "генерация через инжектируемый llm_call",
        "verdict": verdict,
    }


def freeze_rubric() -> dict:
    """Хеш рубрики ДО прогона (смена рубрики = новый experiment_id)."""
    return {"experiment_id": EXPERIMENT_ID, "rubric": RUBRIC}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mca-18 paired replay")
    parser.add_argument("--dry-run", action="store_true",
                        help="offline-прогон с заглушкой генератора "
                             "(без LLM-вызовов; проверка контура)")
    args = parser.parse_args(argv)

    async def _dry_llm(messages, scenario, with_rule):
        return f"[dry] {scenario['category']} ответ (rule={with_rule})"

    import asyncio
    report = asyncio.run(run_replay(_dry_llm))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
