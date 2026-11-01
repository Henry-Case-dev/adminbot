"""ER-65 / ER-S42 / ER-09 — снимок фактически отправленных сегментов промптов.

Проверяет ДВА независимых свойства артефакта
`plans/features/evol/evidence/er65/sent-segments.json`:

1. **Регенерируемость и байтовая стабильность.** Снимок пересобирается
   штатной командой из заголовка артефакта
   (`py -3 tools/er65_prompt_segment_snapshot.py --check`), которая делает два
   прогона в РАЗНЫХ процессах и сравнивает их между собой и с закоммиченным
   файлом. Модель не вызывается: payload снимается на транспортной границе
   (`llm.generate` / `chat_with_tools`), сеть блокируется, PG недоступен.
   Любая правка канона, порядка сборки, набора инструментов или слоёв хода
   немедленно ломает это сравнение — обновлять снимок можно только осознанно,
   командой `--write`.

2. **Самодостаточность артефакта.** Тест НЕ доверяет флагам, которые посчитал
   сам инструмент: он заново считает `sha256`, длины и позиции блоков из поля
   `text` каждого сегмента и проверяет полноту/порядок канонических блоков.
   Так «тихо исчезнувший» или переставленный блок виден даже при неизменном
   наборе стадий.

Чего тест не проверяет (нужен живой вызов модели): что провайдер принял
payload, `usage`, соблюдение инструкций моделью и что боевой чат получает тот
же текст при персистентных override владельца.

TEST-LIFECYCLE: CONTRACT owner=EVOL-016/ER-65 (снимок отправленных сегментов)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "er65_prompt_segment_snapshot.py")
ARTIFACT = os.path.join(ROOT, "plans", "features", "evol", "evidence", "er65",
                        "sent-segments.json")
MARKDOWN = os.path.join(ROOT, "plans", "features", "evol", "evidence", "er65",
                        "sent-segments.md")

EXPECTED_STAGE_IDS = {
    "direct.l1_planner",
    "direct.l1_planner.tools",
    "direct.l2_writer.direct",
    "direct.l2_writer.tool_evidence",
    "direct.l2_writer.deterministic_fallback_plan",
    "direct.tool_phase.model_driven",
    "direct.single.legacy_no_tools",
    "direct.system2.stage1",
    "direct.system2.stage2",
    "direct.l2_writer.layered",
    "direct.l2_writer.fallback_model_repack",
    "direct.l2_writer.fallback_model_capacity",
    "factcheck.single",
    "factcheck.stage1_analyst",
    "factcheck.stage2_verbalizer",
    "initiative.l1_planner",
    "initiative.l2_writer",
}


def _snapshot() -> dict:
    with open(ARTIFACT, encoding="utf-8") as handle:
        return json.load(handle)


def _stage(snapshot: dict, stage_id: str) -> dict:
    for stage in snapshot["stages"]:
        if stage["stage_id"] == stage_id:
            return stage
    raise AssertionError(f"стадия отсутствует в снимке: {stage_id}")


def _message(stage: dict, role: str) -> dict:
    for message in stage["messages"]:
        if message["role"] == role:
            return message
    raise AssertionError(f"{stage['stage_id']}: нет сегмента role={role}")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 1. регенерируемость + байтовая стабильность (штатная команда) ───────────

def test_snapshot_regenerates_byte_stable_from_code():
    """Команда перегенерации воспроизводит артефакт байт-в-байт.

    `--check` поднимает ДВА независимых процесса, сравнивает их между собой
    (детерминированность) и с закоммиченным файлом (регенерируемость из кода).
    """
    assert os.path.exists(ARTIFACT), "нет снимка сегментов"
    assert os.path.exists(MARKDOWN), "нет markdown-описания снимка"
    result = subprocess.run([sys.executable, TOOL, "--check"], cwd=ROOT,
                            capture_output=True, timeout=600)
    output = (result.stdout + result.stderr).decode("utf-8", "replace")
    assert result.returncode == 0, (
        "снимок не воспроизводится (канон/порядок сборки разошлись):\n"
        + output[-3000:])
    assert "two isolated processes identical" in output


# ── 2. состав стадий и структура сообщений ─────────────────────────────────

def test_all_stages_captured_with_canonical_message_structure():
    snapshot = _snapshot()
    stage_ids = {stage["stage_id"] for stage in snapshot["stages"]}
    assert stage_ids == EXPECTED_STAGE_IDS
    assert snapshot["summary"]["stages"] == len(EXPECTED_STAGE_IDS)
    for stage in snapshot["stages"]:
        messages = stage["messages"]
        assert messages, stage["stage_id"]
        assert messages[0]["role"] == "system", (
            f"{stage['stage_id']}: system обязан быть на индексе 0")
        assert [m["index"] for m in messages] == list(range(len(messages)))
        assert {"system", "user"} <= {m["role"] for m in messages}
        for message in messages:
            assert message["sha256"] == _sha256(message["text"]), (
                f"{stage['stage_id']}#{message['index']}: sha256 не сходится")
            assert message["chars"] == len(message["text"])
            assert message["bytes_utf8"] == len(message["text"].encode("utf-8"))


def test_tool_phase_segment_carries_tool_schemas():
    stage = _stage(_snapshot(), "direct.tool_phase.model_driven")
    assert stage["tools"]["count"] == len(stage["tools"]["names"]) > 0
    assert "execute_web_search" in stage["tools"]["names"]
    system = _message(stage, "system")["text"]
    user = _message(stage, "user")["text"]
    # Канон канала — тот же, что в реестре, и он первый в системе.
    assert system.startswith(_resolved_text(stage,
                                            "prompts.direct_chat_system_prompt"))
    assert "почему после релиза 2.58.147 упал сервис" in user


# ── 3. канонические блоки: наличие, ревизия/печать, порядок ────────────────

def _resolutions(stage: dict, key: str) -> list:
    return [row for row in stage["prompt_resolutions"] if row["key"] == key]


def _resolved_text(stage: dict, key: str) -> str:
    rows = _resolutions(stage, key)
    assert rows, f"{stage['stage_id']}: канон {key} не резолвился"
    return _snapshot()["prompt_revisions"][rows[0]["sha256_12"]]["text"]


def _present_in(text: str, joined: str) -> bool:
    """Присутствие блока с допуском на подстановку `{max_symbols}`."""
    if not text:
        return True
    if text in joined:
        return True
    parts = [part for part in re.split(r"\{[A-Za-z_][A-Za-z0-9_]*\}", text)
             if part]
    cursor = 0
    for part in parts:
        found = joined.find(part, cursor)
        if found < 0:
            return False
        cursor = found + len(part)
    return True


def test_expected_canon_present_in_every_stage():
    """Каждый ожидаемый канон-ключ доехал до фактического сегмента.

    Наличие пересчитывается из фактического текста сегмента: тест не верит
    флагу `found_in_segment`, который посчитал инструмент.
    """
    snapshot = _snapshot()
    revisions = snapshot["prompt_revisions"]
    for stage in snapshot["stages"]:
        assert stage["expected_prompt_keys"], stage["stage_id"]
        joined = "\n".join(m["text"] for m in stage["messages"])
        for key in stage["expected_prompt_keys"]:
            rows = _resolutions(stage, key)
            assert rows, f"{stage['stage_id']}: {key} не резолвился вовсе"
            texts = [revisions[row["sha256_12"]]["text"] for row in rows
                     if row["sha256_12"] in revisions]
            assert texts, f"{stage['stage_id']}: {key} без текста редакции"
            assert any(_present_in(text, joined) for text in texts), (
                f"{stage['stage_id']}: канон {key} отсутствует в сегменте")
            for row in rows:
                assert row["revision"].startswith("act:")
                text = revisions[row["sha256_12"]]["text"]
                assert hashlib.sha256(text.encode("utf-8")) \
                    .hexdigest()[:12] == row["sha256_12"]
                if row["block_id"] and row["factory_revision"]:
                    assert row["factory_revision"].startswith("fac:")
                    assert row["factory_seal"], (
                        f"{key}: у блока реестра нет печати")


def test_layered_writer_keeps_declared_block_order():
    """Слои хода идут в том порядке, в каком их собирает код."""
    stage = _stage(_snapshot(), "direct.l2_writer.layered")
    system = _message(stage, "system")["text"]
    user = _message(stage, "user")["text"]
    order = ["layer:character_block", "layer:style_requests"]
    positions = [system.index(_layer_text(label)) for label in order]
    assert positions == sorted(positions)
    assert _resolutions(stage, "prompts.direct_chat_verbalizer_system_prompt")
    assert system.startswith(
        _resolved_text(stage,
                       "prompts.direct_chat_verbalizer_system_prompt").rstrip())
    user_order = ["layer:time_line", "layer:plan_block",
                  "layer:speech_understanding", "layer:verified_lessons",
                  "layer:user_block_global_context",
                  "layer:tool_evidence_block"]
    user_positions = [user.index(_layer_text(label)) for label in user_order]
    assert user_positions == sorted(user_positions)
    # Закрывающее требование — последнее в user-части.
    closing = _stage(_snapshot(), "direct.l2_writer.direct")
    assert user.rstrip().endswith(_closing_text(closing))


def test_factcheck_keeps_genre_canon_and_critique_section():
    stage = _stage(_snapshot(), "factcheck.single")
    system = _message(stage, "system")["text"]
    user = _message(stage, "user")["text"]
    genre = _resolved_text(stage, "prompts.factcheck_system_prompt")
    assert system.startswith(genre.split("{max_symbols}")[0].rstrip())
    assert "КРИТИЧЕСКИЙ РАЗНОС" in system
    assert _resolutions(stage, "prompts.factcheck_critique_directive")
    # claim идёт ПЕРЕД выдачей поиска (канон build_user_content).
    assert user.index("<claim>") < user.index("<search_results>")


def test_factcheck_two_call_isolates_analyst_and_verbalizer():
    snapshot = _snapshot()
    analyst = _message(_stage(snapshot, "factcheck.stage1_analyst"),
                       "system")["text"]
    verbalizer_stage = _stage(snapshot, "factcheck.stage2_verbalizer")
    verbalizer = _message(verbalizer_stage, "system")["text"]
    assert analyst != verbalizer
    assert _resolutions(
        _stage(snapshot, "factcheck.stage1_analyst"),
        "prompts.factcheck_analyst_system_prompt")
    assert _resolutions(verbalizer_stage,
                        "prompts.factcheck_verbalizer_system_prompt")
    # Stage-2 получает JSON справку, а не сырую «кашу» логов.
    assert _message(verbalizer_stage, "user")["text"].startswith(
        "АНАЛИЗ (JSON):")


# ── 4. деградированные пути ────────────────────────────────────────────────

def test_l1_outage_path_sends_no_planner_payload_but_writes_answer():
    stage = _stage(_snapshot(), "direct.l2_writer.deterministic_fallback_plan")
    assert "детерминирован" in stage["title"].lower()
    assert _message(stage, "system")["chars"] > 0
    assert _message(stage, "user")["chars"] > 0
    # План-блок в user-части есть, хотя LLM-планер упал.
    assert "<Response_Plan>" in _message(stage, "user")["text"]


def test_fallback_model_repack_and_capacity_are_distinct():
    snapshot = _snapshot()
    repack = _stage(snapshot, "direct.l2_writer.fallback_model_repack")
    capacity = _stage(snapshot, "direct.l2_writer.fallback_model_capacity")
    assert any("400" in note for note in capacity["notes"])
    assert any("fallback_window_exceeded" in note for note in capacity["notes"])
    capacity_user = _message(capacity, "user")["text"]
    assert "[CAPACITY]" in capacity_user, (
        "честная capacity-пометка обязана быть в пакете")
    repack_user = _message(repack, "user")["text"]
    assert "[CAPACITY]" not in repack_user
    # Пересборка сохраняет слои хода, capacity-исход честно теряет материалы.
    repack_labels = {b["label"] for b in _message(repack, "user")["blocks"]}
    capacity_labels = set()
    for message in capacity["messages"]:
        capacity_labels.update(b["label"] for b in message["blocks"])
    for layer in ("layer:plan_block", "layer:speech_understanding",
                  "layer:verified_lessons",
                  "layer:user_block_global_context"):
        assert layer in repack_labels, f"пересборка потеряла слой {layer}"
        assert layer not in capacity_labels, (
            f"capacity-исход не должен молча сохранять {layer}")
    assert "<Tool_Evidence>" in capacity_user


def test_known_block_order_delta_in_fallback_repack_is_recorded():
    """Пересборка под окно fallback ставит evidence ПОСЛЕ закрывающего блока.

    Это наблюдаемое поведение существующего адаптера (LLMClient применяет его
    при переключении модели), а не решение снимка: фиксируем его явно, чтобы
    изменение порядка не проходило незаметно.
    """
    snapshot = _snapshot()
    assert snapshot["summary"]["stages_with_order_violations"] == [
        "direct.l2_writer.fallback_model_repack"]
    stage = _stage(snapshot, "direct.l2_writer.fallback_model_repack")
    labels = [b["label"] for b in _message(stage, "user")["blocks"]]
    assert labels.index("canon:no_meta_closing") < labels.index(
        "layer:tool_evidence_block")
    # В первичной сборке порядок обратный — и это тоже проверяется.
    layered = _stage(snapshot, "direct.l2_writer.layered")
    primary = [b["label"] for b in _message(layered, "user")["blocks"]]
    assert primary.index("layer:tool_evidence_block") < primary.index(
        "canon:no_meta_closing")


def test_initiative_uses_same_planner_and_writer_canon():
    snapshot = _snapshot()
    plan_stage = _stage(snapshot, "initiative.l1_planner")
    write_stage = _stage(snapshot, "initiative.l2_writer")
    assert _resolutions(plan_stage, "prompts.direct_l1_planner_system_prompt")
    assert _resolutions(write_stage,
                        "prompts.direct_chat_verbalizer_system_prompt")
    assert _message(plan_stage, "user")["text"].count("[УСЛОВИЯ]") == 1
    assert "автономная инициатива" in _message(plan_stage, "user")["text"]


# ── 5. детерминированность ─────────────────────────────────────────────────

def test_determinism_recorded_in_artifact():
    snapshot = _snapshot()
    determinism = snapshot["determinism"]
    assert determinism["runs"] == 2
    assert determinism["isolated_processes"] is True
    assert determinism["identical"] is True
    assert determinism["compared_stages"] == snapshot["summary"]["stages"]
    assert determinism["compared_segments"] == \
        snapshot["summary"]["message_segments"]
    assert len(determinism["snapshot_core_sha256"]) == 64
    assert snapshot["environment"]["seal_problems"] == {}
    assert snapshot["environment"]["gate_mode"].startswith("offline")


# ── 6. описательный markdown не отстал от снимка ───────────────────────────

def test_markdown_lists_every_stage():
    with open(MARKDOWN, encoding="utf-8") as handle:
        body = handle.read()
    snapshot = _snapshot()
    for stage in snapshot["stages"]:
        assert f"`{stage['stage_id']}`" in body, stage["stage_id"]
    assert "py -3 tools/er65_prompt_segment_snapshot.py --write" in body
    assert "Что НЕ доказано" in body


# ── вспомогательное: реальные тексты слоёв из снимка ───────────────────────

def _layer_text(label: str) -> str:
    """Текст слоя берётся из самого снимка (без констант в тесте)."""
    snapshot = _snapshot()
    for stage in snapshot["stages"]:
        for message in stage["messages"]:
            for block in message["blocks"]:
                if block["label"] == label:
                    return message["text"][block["offset"]:
                                           block["offset"] + block["chars"]]
    raise AssertionError(f"слой {label} отсутствует в снимке")


def _closing_text(stage: dict) -> str:
    for message in stage["messages"]:
        for block in message["blocks"]:
            if block["label"] == "canon:no_meta_closing":
                return message["text"][block["offset"]:
                                       block["offset"] + block["chars"]]
    raise AssertionError("закрывающий блок отсутствует в снимке")
