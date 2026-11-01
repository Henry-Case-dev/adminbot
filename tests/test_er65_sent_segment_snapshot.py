"""ER-65 / ER-S42 / ER-09 — снимок фактически отправленных сегментов промптов.

Проверяет ДВА независимых свойства артефакта
`plans/features/evol/evidence/er65/sent-segments.json`:

1. **Регенерируемость и байтовая стабильность.** Снимок пересобирается
   штатной командой из заголовка артефакта
   (`py -3 tools/er65_prompt_segment_snapshot.py --check`), которая делает два
   прогона в РАЗНЫХ процессах и сравнивает их между собой и с закоммиченным
   файлом. Модель не вызывается: payload снимается на транспортной границе
   (`llm.generate` / `llm.generate_chat`), сеть блокируется, PG недоступен.
   Любая правка канона, порядка сборки, набора слоёв композера, схем
   инструментов или tool-раундов немедленно ломает это сравнение — обновлять
   снимок можно только осознанно, командой `--write`.

2. **Самодостаточность артефакта.** Тест НЕ доверяет флагам, которые посчитал
   сам инструмент: он заново считает `sha256`, длины и порядок блоков из поля
   `text` каждого сегмента, сам объявляет ожидаемые канон-ключи по стадиям и
   сам проверяет боевые слои (Core / identity / Expression) в фактических
   байтах system. Так «тихо исчезнувший» слой, блок или tool-раунд виден даже
   при неизменном наборе стадий.

Чего тест не проверяет (нужен живой вызов модели): приём payload провайдером,
`usage`, соблюдение инструкций моделью и точные боевые тексты документов
владельца из PG (в снимке — заводские редакции Core/Expression и объявленный
`character_block`).

TEST-LIFECYCLE: CONTRACT owner=EVOL-016/ER-65 (снимок отправленных сегментов)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "er65_prompt_segment_snapshot.py")
EVIDENCE = os.path.join(ROOT, "plans", "features", "evol", "evidence", "er65")
ARTIFACT = os.path.join(EVIDENCE, "sent-segments.json")
MARKDOWN = os.path.join(EVIDENCE, "sent-segments.md")

MODE_PROD = "prod_on"
MODE_OFF = "factory_off"

#: Независимая константа теста (НЕ читается из артефакта): какие стадии обязаны
#: существовать и какие канон-ключи обязаны доехать до модели.
EXPECTED_STAGES = {
    ("direct.l1_planner", MODE_PROD):
        ("prompts.direct_l1_planner_system_prompt",),
    ("direct.l1_planner.tools", MODE_PROD):
        ("prompts.direct_l1_planner_system_prompt",),
    ("direct.l2_writer.direct", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.tool_evidence", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.deterministic_fallback_plan", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.tool_phase.model_driven", MODE_PROD):
        ("prompts.direct_chat_system_prompt",),
    ("direct.tool_phase.tool_round", MODE_PROD):
        ("prompts.direct_chat_system_prompt",),
    ("direct.single.legacy_no_tools", MODE_PROD):
        ("prompts.direct_chat_system_prompt",),
    ("direct.system2.stage1", MODE_PROD):
        ("prompts.direct_chat_synthesizer_system_prompt",),
    ("direct.system2.stage2", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.layered", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.fallback_model_repack", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.fallback_model_capacity", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("factcheck.single", MODE_PROD):
        ("prompts.factcheck_system_prompt",
         "prompts.factcheck_critique_directive"),
    ("factcheck.stage1_analyst", MODE_PROD):
        ("prompts.factcheck_analyst_system_prompt",),
    ("factcheck.stage2_verbalizer", MODE_PROD):
        ("prompts.factcheck_verbalizer_system_prompt",),
    ("initiative.l1_planner", MODE_PROD):
        ("prompts.direct_l1_planner_system_prompt",),
    ("initiative.l2_writer", MODE_PROD):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    # вторичный заводской OFF-контур (помечен как НЕ боевой)
    ("direct.l1_planner", MODE_OFF):
        ("prompts.direct_l1_planner_system_prompt",),
    ("direct.l2_writer.direct", MODE_OFF):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.tool_phase.model_driven", MODE_OFF):
        ("prompts.direct_chat_system_prompt",),
    ("direct.tool_phase.tool_round", MODE_OFF):
        ("prompts.direct_chat_system_prompt",),
    ("direct.system2.stage1", MODE_OFF):
        ("prompts.direct_chat_synthesizer_system_prompt",),
    ("direct.system2.stage2", MODE_OFF):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.layered", MODE_OFF):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.fallback_model_repack", MODE_OFF):
        ("prompts.direct_chat_verbalizer_system_prompt",),
    ("direct.l2_writer.fallback_model_capacity", MODE_OFF):
        ("prompts.direct_chat_verbalizer_system_prompt",),
}

#: Боевые оси, которые обязаны быть включены в основном режиме.
PROD_GATES_ON = (
    "unified_composer_enabled", "character_core_enabled",
    "speech_style_policy_enabled", "humor_library_enabled",
    "humor_feedback_enabled", "humor_craft_enabled",
    "expression_examples_enabled", "persona_enabled",
    "character_layers_enabled", "smart_verbalizer_modes_enabled",
    "response_plan_enabled",
)

#: Стадии L2 Writer, где боевая сборка обязана содержать Core и Expression.
LAYERED_PROD_STAGES = (
    "direct.l2_writer.direct",
    "direct.l2_writer.tool_evidence",
    "direct.l2_writer.layered",
    "initiative.l2_writer",
)


def _snapshot() -> dict:
    with open(ARTIFACT, encoding="utf-8") as handle:
        return json.load(handle)


def _stage(snapshot: dict, stage_id: str, mode: str = MODE_PROD) -> dict:
    for stage in snapshot["stages"]:
        if stage["stage_id"] == stage_id and stage["mode"] == mode:
            return stage
    raise AssertionError(f"стадия отсутствует в снимке: {stage_id} [{mode}]")


def _message(stage: dict, role: str) -> dict:
    for message in stage["messages"]:
        if message["role"] == role:
            return message
    raise AssertionError(f"{stage['stage_id']}: нет сегмента role={role}")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _labels(stage: dict, role: str) -> list:
    return [block["label"] for block in _message(stage, role)["blocks"]]


def _layer_text(snapshot: dict, label: str, stage: dict | None = None) -> str:
    """Текст слоя берётся из самого снимка (без констант в тесте).

    Ищем сначала в указанной стадии: одноимённые слои разных стадий могут
    нести разный текст (например evidence хода с инструментами).
    """
    stages = [stage] if stage is not None else snapshot["stages"]
    for item in stages:
        for message in item["messages"]:
            for block in message["blocks"]:
                if block["label"] == label:
                    return message["text"][block["offset"]:
                                           block["offset"] + block["chars"]]
    raise AssertionError(f"слой {label} отсутствует в снимке")


# ── 1. регенерируемость + байтовая стабильность (штатная команда) ───────────

def test_snapshot_regenerates_byte_stable_from_code():
    """Команда перегенерации воспроизводит артефакт байт-в-байт.

    `--check` поднимает ДВА независимых процесса, сравнивает их между собой
    (детерминированность) и с закоммиченным файлом (регенерируемость из кода).
    """
    assert os.path.exists(ARTIFACT), "нет снимка сегментов"
    assert os.path.exists(MARKDOWN), "нет markdown-описания снимка"
    result = subprocess.run([sys.executable, TOOL, "--check"], cwd=ROOT,
                            capture_output=True, timeout=1800)
    output = (result.stdout + result.stderr).decode("utf-8", "replace")
    assert result.returncode == 0, (
        "снимок не воспроизводится (канон/слои/порядок сборки разошлись):\n"
        + output[-3000:])
    assert "two isolated processes identical" in output


# ── 2. боевая конфигурация гейтов (B1) ─────────────────────────────────────

def test_primary_mode_is_production_gate_configuration():
    env = _snapshot()["environment"]
    assert env["primary_mode"] == MODE_PROD
    assert env["secondary_mode_note"], "вторичный OFF обязан быть помечен"
    assert "НЕ является" in env["secondary_mode_note"]
    gates = env["gates_prod"]
    for axis in PROD_GATES_ON:
        assert gates[axis] is True, f"ось {axis} выключена в боевой карте"
    assert env["composer_enabled_prod"] is True
    assert env["composer_env_enabled_prod"] is True
    assert env["gates_provenance"], "карта гейтов без источников"
    assert any("release-2.58.86" in source
               for source in env["gates_provenance"])
    assert any("raw_new_code_A.json" in source
               for source in env["gates_provenance"])
    assert env["network"].startswith("blocked")
    assert "PG" in env["config_layer"]


def test_production_stages_carry_core_identity_and_expression():
    """Боевая сборка: Core / identity / Expression реально в system.

    Проверка идёт по фактическим байтам сегментов и по манифесту композера,
    а не по флагу инструмента.
    """
    snapshot = _snapshot()
    for stage_id in LAYERED_PROD_STAGES:
        stage = _stage(snapshot, stage_id)
        layers = {layer["layer"]: layer for layer in stage["composer_layers"]}
        assert layers, f"{stage_id}: нет манифеста композера"
        assert layers["core"]["rendered"] is True, (
            f"{stage_id}: слой Core не отрендерен")
        assert layers["expression"]["rendered"] is True, (
            f"{stage_id}: слой Expression не отрендерен")
        assert layers["channel_contract"]["rendered"] is True
        labels = _labels(stage, "system")
        assert any(label.startswith("layer:core:") for label in labels), labels
        assert any(label.startswith("layer:expression:") for label in labels), \
            labels
        system = _message(stage, "system")["text"]
        assert "<Expression_Settings>" in system
    # identity: объявленный character_block доезжает до system слоем identity
    layered = _stage(snapshot, "direct.l2_writer.layered")
    identity = [layer for layer in layered["composer_layers"]
                if layer["layer"] == "identity"]
    assert identity and identity[0]["rendered"] is True
    assert any(label.startswith("layer:identity:")
               for label in _labels(layered, "system"))
    # вторичный OFF-контур НЕ содержит этих слоёв — иначе метка режима врёт
    off = _stage(snapshot, "direct.l2_writer.layered", MODE_OFF)
    assert not off["composer_layers"], "OFF-контур не должен иметь манифест ON"
    assert "<Expression_Settings>" not in _message(off, "system")["text"]


def test_lessons_and_speech_live_in_system_on_production_path():
    """При ON speech/lessons рендерит композер в system, а не дублирует user."""
    snapshot = _snapshot()
    stage = _stage(snapshot, "direct.l2_writer.layered")
    system = _message(stage, "system")["text"]
    user = _message(stage, "user")["text"]
    assert "<Verified_Lessons>" in system and "<Verified_Lessons>" not in user
    assert "<Speech_Understanding>" in system
    assert "<Style_Requests>" in system
    off = _stage(snapshot, "direct.l2_writer.layered", MODE_OFF)
    off_user = _message(off, "user")["text"]
    off_system = _message(off, "system")["text"]
    assert "<Verified_Lessons>" in off_user and \
        "<Verified_Lessons>" not in off_system


# ── 3. tool-раунды (B2) ────────────────────────────────────────────────────

def test_model_driven_tool_loop_captures_assistant_and_tool_segments():
    """Реальный tool-цикл: раунд 2 несёт assistant.tool_calls и role=tool."""
    snapshot = _snapshot()
    for mode in (MODE_PROD, MODE_OFF):
        stage = _stage(snapshot, "direct.tool_phase.tool_round", mode)
        assert stage["roles"] == ["system", "user", "assistant", "tool"]
        assistant = _message(stage, "assistant")
        calls = assistant["tool_calls"]
        assert calls, "assistant-сообщение без tool_calls"
        assert calls[0]["name"] == "execute_web_search"
        assert calls[0]["id"], "tool_call без id"
        assert calls[0]["arguments_chars"] > 0
        tool = _message(stage, "tool")
        assert tool["chars"] > 0, "сообщение role=tool без результата"
        assert any(block["label"] == "layer:tool_result"
                   for block in tool["blocks"])
        # Раунд 1 — тот же system+user, но без tool-сообщений.
        first = _stage(snapshot, "direct.tool_phase.model_driven", mode)
        assert first["roles"] == ["system", "user"]
    assert snapshot["summary"]["tool_segments"] >= 2
    assert snapshot["summary"]["assistant_segments"] >= 2
    # `developer` не используется ни одной стадией — по фактическим ролям.
    assert "developer" not in snapshot["summary"]["roles_observed"]


def test_l1_path_prefers_planner_payload_without_tool_roles():
    snapshot = _snapshot()
    stage = _stage(snapshot, "direct.l2_writer.tool_evidence")
    assert stage["roles"] == ["system", "user"]
    user = _message(stage, "user")["text"]
    assert "<Tool_Evidence>" in user
    assert "upstream 502" in user or "результат инструмента" in user
    assert stage["tools"]["count"] == 0, (
        "L1-путь: детерминированная tool-фаза, LLM-payload инструментов нет")


# ── 4. состав стадий и структура сообщений ─────────────────────────────────

def test_all_stages_captured_with_canonical_message_structure():
    snapshot = _snapshot()
    keys = {(stage["stage_id"], stage["mode"]) for stage in snapshot["stages"]}
    assert keys == set(EXPECTED_STAGES)
    assert snapshot["summary"]["stages"] == len(EXPECTED_STAGES)
    assert snapshot["summary"]["stages_factory_off"] == sum(
        1 for _sid, mode in EXPECTED_STAGES if mode == MODE_OFF)
    for stage in snapshot["stages"]:
        messages = stage["messages"]
        assert messages, stage["stage_id"]
        assert messages[0]["role"] == "system", (
            f"{stage['stage_id']}: system обязан быть на индексе 0")
        assert [m["index"] for m in messages] == list(range(len(messages)))
        assert {"system", "user"} <= {m["role"] for m in messages}
        assert stage["roles"] == [m["role"] for m in messages]
        for message in messages:
            assert message["sha256"] == _sha256(message["text"]), (
                f"{stage['stage_id']}#{message['index']}: sha256 не сходится")
            assert message["chars"] == len(message["text"])
            assert message["bytes_utf8"] == len(message["text"].encode("utf-8"))
        # Порядок блоков покрывает текст без дыр в байтах.
        for message in messages:
            covered = sum(block["chars"] for block in message["blocks"])
            assert covered == message["chars"], (
                f"{stage['stage_id']}#{message['index']}: блоки не покрывают "
                "сегмент целиком")


def test_expected_canon_present_in_every_stage():
    """Каждый ожидаемый канон-ключ доехал до фактического сегмента.

    Ожидания берутся из константы теста (не из артефакта), наличие
    пересчитывается из фактического текста сегмента.
    """
    snapshot = _snapshot()
    revisions = snapshot["prompt_revisions"]
    for stage in snapshot["stages"]:
        expected = EXPECTED_STAGES[(stage["stage_id"], stage["mode"])]
        assert tuple(stage["expected_prompt_keys"]) == expected, (
            f"{stage['stage_id']}[{stage['mode']}]: набор ожиданий разошёлся")
        joined = "\n".join(m["text"] for m in stage["messages"])
        for key in expected:
            rows = _resolutions(stage, key)
            assert rows, f"{stage['stage_id']}: {key} не резолвился вовсе"
            texts = [revisions[row["sha256_12"]]["text"] for row in rows
                     if row["sha256_12"] in revisions]
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
    snapshot = _snapshot()
    stage = _stage(snapshot, "direct.l2_writer.layered")
    system = _message(stage, "system")["text"]
    labels = _labels(stage, "system")
    # Порядок слоёв в system: канал → Core → identity → lessons → план →
    # speech_base → Expression (как в compose_prompt: шаги 6 → 7).
    order = [next(label for label in labels if label.startswith(prefix))
             for prefix in ("layer:channel_contract:", "layer:core:",
                            "layer:identity:", "layer:context_lessons:",
                            "layer:response_plan:", "layer:speech_base",
                            "layer:expression:")]
    positions = [system.index(_layer_text(snapshot, label, stage))
                 for label in order]
    assert positions == sorted(positions), order
    user = _message(stage, "user")["text"]
    user_order = ["layer:time_line", "layer:plan_block",
                  "layer:user_block_global_context",
                  "layer:tool_evidence_block"]
    user_positions = [user.index(_layer_text(snapshot, label, stage))
                      for label in user_order]
    assert user_positions == sorted(user_positions)
    # Закрывающее требование — последнее в user-части.
    assert user.rstrip().endswith(
        _layer_text(snapshot, "canon:no_meta_closing", stage))


def test_factcheck_keeps_genre_canon_and_critique_section():
    snapshot = _snapshot()
    stage = _stage(snapshot, "factcheck.single")
    system = _message(stage, "system")["text"]
    user = _message(stage, "user")["text"]
    genre = _resolved_text(stage, "prompts.factcheck_system_prompt")
    assert system.startswith(genre.split("{max_symbols}")[0].rstrip())
    assert "КРИТИЧЕСКИЙ РАЗНОС" in system
    assert _resolutions(stage, "prompts.factcheck_critique_directive")
    assert user.index("<claim>") < user.index("<search_results>")


def test_factcheck_two_call_isolates_analyst_and_verbalizer():
    snapshot = _snapshot()
    analyst_stage = _stage(snapshot, "factcheck.stage1_analyst")
    verbalizer_stage = _stage(snapshot, "factcheck.stage2_verbalizer")
    assert _message(analyst_stage, "system")["text"] != \
        _message(verbalizer_stage, "system")["text"]
    assert _resolutions(analyst_stage,
                        "prompts.factcheck_analyst_system_prompt")
    assert _resolutions(verbalizer_stage,
                        "prompts.factcheck_verbalizer_system_prompt")
    assert _message(verbalizer_stage, "user")["text"].startswith(
        "АНАЛИЗ (JSON):")


# ── 5. деградированные пути ────────────────────────────────────────────────

def test_l1_outage_path_sends_no_planner_payload_but_writes_answer():
    stage = _stage(_snapshot(), "direct.l2_writer.deterministic_fallback_plan")
    assert "детерминирован" in stage["title"].lower()
    assert _message(stage, "system")["chars"] > 0
    assert _message(stage, "user")["chars"] > 0
    assert "<Response_Plan>" in _message(stage, "user")["text"]


def test_fallback_model_repack_and_capacity_are_distinct():
    snapshot = _snapshot()
    repack = _stage(snapshot, "direct.l2_writer.fallback_model_repack")
    capacity = _stage(snapshot, "direct.l2_writer.fallback_model_capacity")
    assert any("5000" in note for note in repack["notes"])
    assert any("fallback_window_exceeded" in note for note in capacity["notes"])
    capacity_user = _message(capacity, "user")["text"]
    assert "[CAPACITY]" in capacity_user
    assert "[CAPACITY]" not in _message(repack, "user")["text"]
    # Пересборка при достаточном окне сохраняет ВСЕ слои хода и закрывающее
    # требование; capacity-исход честно теряет материалы и помечает потерю.
    repack_labels = set(_labels(repack, "user"))
    capacity_labels = set()
    for message in capacity["messages"]:
        capacity_labels.update(block["label"] for block in message["blocks"])
    for layer in ("layer:time_line", "layer:plan_block",
                  "layer:user_block_global_context",
                  "layer:tool_evidence_block", "canon:no_meta_closing"):
        assert layer in repack_labels, f"пересборка потеряла слой {layer}"
    for layer in ("layer:plan_block", "layer:user_block_global_context",
                  "layer:tool_evidence_block"):
        assert layer not in capacity_labels, (
            f"capacity-исход не должен молча сохранять {layer}")
    assert "<Tool_Evidence>" in capacity_user
    # speech/lessons на боевом пути живут в system, поэтому в parts адаптера
    # их нет — и «потеря» capacity их не касается.
    system = _message(repack, "system")["text"]
    assert "<Verified_Lessons>" in system
    assert "<Speech_Understanding>" in system


def test_known_block_order_delta_in_fallback_repack_is_recorded():
    """Пересборка под окно fallback ставит evidence ПОСЛЕ закрывающего блока.

    Это наблюдаемое поведение существующего адаптера (дефект вынесен в
    отдельную полосу), а не решение снимка: фиксируем явно, чтобы изменение
    порядка не проходило незаметно.
    """
    snapshot = _snapshot()
    assert snapshot["summary"]["stages_with_order_violations"] == [
        "direct.l2_writer.fallback_model_repack"]
    stage = _stage(snapshot, "direct.l2_writer.fallback_model_repack")
    labels = _labels(stage, "user")
    assert labels.index("canon:no_meta_closing") < labels.index(
        "layer:tool_evidence_block")
    layered = _stage(snapshot, "direct.l2_writer.layered")
    primary = _labels(layered, "user")
    assert primary.index("layer:tool_evidence_block") < primary.index(
        "canon:no_meta_closing")


def test_initiative_uses_same_planner_and_writer_canon():
    snapshot = _snapshot()
    plan_stage = _stage(snapshot, "initiative.l1_planner")
    write_stage = _stage(snapshot, "initiative.l2_writer")
    assert _resolutions(plan_stage, "prompts.direct_l1_planner_system_prompt")
    assert _resolutions(write_stage,
                        "prompts.direct_chat_verbalizer_system_prompt")
    assert "автономная инициатива" in _message(plan_stage, "user")["text"]


# ── 6. детерминированность ─────────────────────────────────────────────────

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


# ── 7. описательный markdown не отстал от снимка ───────────────────────────

def test_markdown_lists_every_stage_and_gate_map():
    with open(MARKDOWN, encoding="utf-8") as handle:
        body = handle.read()
    snapshot = _snapshot()
    for stage in snapshot["stages"]:
        assert f"`{stage['stage_id']}`" in body, stage["stage_id"]
    assert "py -3 tools/er65_prompt_segment_snapshot.py --write" in body
    assert "## Боевая карта гейтов" in body
    assert "Что НЕ доказано" in body
    assert "Ограничения снимка" in body
    assert "не является" in body or "НЕ является" in body
