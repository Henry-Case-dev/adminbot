"""MCA-18 — offline paired replay harness (T-5090, §28.7 `:1594–1596`).

Проверки контура (БЕЗ платных вызовов — генератор фейковый):
  * 30 сценариев, детерминированных, 7 категорий §28.7;
  * рубрика заморожена ДО прогона (experiment_id = хеш рубрики);
  * пары условий на одинаковой модели/контексте; счёт вызовов честный;
  * оценщик СЛЕП: auto_score получает только текст ответа;
  * эффект ≠ шум (R7c): verified только при |Δ| ≥ threshold и > noise;
  * БЕЗ посылки в рабочий чат: харнесс не импортирует telegram-транспорт;
  * авто-оценка вспомогательная (caveat в отчёте).
"""
import json

import pytest

import tools.mca18_paired_replay as replay


def test_scenarios_deterministic_30_and_categories():
    s1 = replay.build_scenarios()
    s2 = replay.build_scenarios()
    assert s1 == s2                              # без ГПСЧ
    assert len(s1) == 30
    cats = {s["category"] for s in s1}
    assert {"joke", "dispute", "help_request", "factcheck", "long_thread",
            "topic_switch", "identity_probe"} <= cats


def test_rubric_frozen_before_run():
    frozen = replay.freeze_rubric()
    assert frozen["experiment_id"] == replay.EXPERIMENT_ID
    assert frozen["rubric"]["version"] == "mca18-replay-rubric-1"
    assert len(frozen["rubric"]["axes"]) == 8
    # experiment_id детерминирован рубрикой (смена рубрики = новый experiment).
    import hashlib
    assert replay.EXPERIMENT_ID == hashlib.sha256(
        json.dumps(replay.RUBRIC, sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()[:16]


@pytest.mark.asyncio
async def test_run_replay_offline_fake_llm_counts_and_no_send():
    calls = {"with": 0, "without": 0}

    async def fake_llm(messages, scenario, with_rule):
        if with_rule:
            calls["with"] += 1
            return "Ну да, чё, по существу: зависает игра."
        calls["without"] += 1
        return "Попробуй перезапустить игру и проверить интернет."
    report = await replay.run_replay(fake_llm)
    expected_history = sum(max(1, s.get("repeats", 1))
                           for s in replay.build_scenarios())
    assert report["scenarios"] == 30
    # H-3 (rework): пары ×≥3 генерации; history-ходы нейтральны и
    # учитываются отдельно (по ходу ветки, включая repeat-блоки).
    assert report["generations_per_condition"] == \
        replay.GENERATIONS_PER_CONDITION == 3
    assert expected_history == 34
    assert report["history_turns"] == expected_history
    assert calls["with"] == expected_history * 3          # парные with ×3
    assert report["paired_generations"] == 2 * calls["with"]
    assert calls["without"] - calls["with"] == report["history_turns"]
    assert report["llm_calls"] == \
        report["paired_generations"] + report["history_turns"]
    assert report["verdict"]["experiment_id"] == replay.EXPERIMENT_ID
    assert "вспомогательная" in report["verdict"]["caveat"]
    # Слепость: auto_score принимает только текст (один аргумент).
    assert replay.auto_score.__code__.co_argcount == 1


@pytest.mark.asyncio
async def test_run_replay_generations_scale_and_spread():
    """H-3 (rework, pre-fix RED): `generations` реально управляет числом
    парных генераций (масштаб ровно ×N; n=1 → не «≥3»), разброс считается
    по репликам (повторы × генерации)."""
    seen: list = []

    async def fake_llm(messages, scenario, with_rule):
        seen.append(1)
        return "короче"
    r1 = await replay.run_replay(fake_llm, generations=1)
    n1 = len(seen)
    r3 = await replay.run_replay(fake_llm, generations=3)
    n3 = len(seen) - n1
    expected_history = 34
    expected_pairs_1 = expected_history * 2
    assert r1["generations_per_condition"] == 1
    assert r1["paired_generations"] == expected_pairs_1
    assert r3["paired_generations"] == expected_pairs_1 * 3
    assert r3["generations_per_condition"] == 3
    assert r3["verdict"]["generations_per_condition"] == 3
    assert n1 == r1["llm_calls"] == r1["paired_generations"] + expected_history
    assert n3 == r3["llm_calls"] == r3["paired_generations"] + expected_history
    assert r3["history_turns"] == expected_history
    # Разброс по репликам: альтернирующие ответы видны как stdev > 0.
    counter = {"n": 0}

    async def noisy_llm(messages, scenario, with_rule):
        counter["n"] += 1
        return "короче" if counter["n"] % 2 else "без маркеров"
    rn = await replay.run_replay(noisy_llm, generations=3)
    assert rn["verdict"]["axes"]["directness"]["stdev_with"] > 0
    assert rn["verdict"]["axes"]["directness"]["stdev_without"] > 0


def test_auto_score_blind_and_deterministic():
    a1 = replay.auto_score("ну да, конечно")
    a2 = replay.auto_score("ну да, конечно")
    assert a1 == a2                              # детерминизм
    assert set(a1) == set(replay.RUBRIC["axes"])
    # Владельческие оси (task_completion и пр.) — 0 (не фейк-автоматика).
    assert a1["task_completion"] == 0


def test_evaluate_effect_vs_noise():
    def _scores(v, n=5):
        return [{"directness": v} for _ in range(n)]
    # Направленный эффект: Δ=1.0 при нулевом разбросе → verified.
    verdict = replay.evaluate(_scores(2.0), _scores(1.0))
    assert verdict["axes"]["directness"]["directed_effect"] is True
    assert verdict["rule_verified"] is True
    # Шум: тот же Δ, но разброс больше эффекта → НЕ «проверено» (R7c).
    noisy_w = [{"directness": 2.0 if i % 2 == 0 else 0.0}
               for i in range(6)]
    noisy_o = [{"directness": 1.0 if i % 2 == 0 else 2.0}
               for i in range(6)]
    verdict2 = replay.evaluate(noisy_w, noisy_o)
    assert verdict2["axes"]["directness"]["directed_effect"] is False
    assert verdict2["rule_verified"] is False


def test_no_telegram_transport_import():
    """Гарантия «без посылки в рабочий чат»: харнесс не импортирует
    telegram-транспорт и не содержит send-вызовов."""
    import sys
    src_path = replay.__file__
    src = open(src_path, encoding="utf-8").read()
    for token in ("telegram", "aiogram", "send_message", "bot.send"):
        assert token not in src, token
    assert sys.modules.get("telegram") is None or \
        "mca18" not in str(getattr(sys.modules.get("telegram"), "__name__",
                                   ""))


def test_cli_dry_run_exit_zero(capsys):
    rc = replay.main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["scenarios"] == 30
    assert report["no_send_guarantee"]
