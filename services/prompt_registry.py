"""SOUL-1 / W1 — Prompt Registry: единый управляемый реестр речевых инструкций.

Нормативная база (обязательные источники слайса):
  * ``plans/features/soul-1/source-architectural-clarification.md`` §3.1–3.4
    («No Hidden Behavioral Prompts»: у любой речевой инструкции есть стабильный
    ID, назначение, factory-ревизия, active-ревизия, scope, effective-источник,
    включённость, история/откат, потребители и точка композиции; «никаких
    речевых инструкций, видимых лишь в Python или SQL»);
  * §4.1–4.6 (версионированные Factory Defaults: runtime использует
    эффективную активную конфигурацию, а не скрытый кодовый дубль);
  * §1.2 + §7.2 (старый речевой канон уходит из effective-слоя, значения
    остаются в аварийной копии; миграция идемпотентна и обратима);
  * ``design-source-of-truth.md`` §1.1–1.2 (schema источников), §3 п.1
    (переиспользование ``bot_settings``/``ConfigCache``/RBAC —
    второй config service НЕ создаётся), §8 п.7 (прецедент
    ``strip_cap_phrases``);
  * ``design-composer-contract.md`` §3 (таксономия слоёв и точки композиции)
    и §4 (реестр известных «токсичных» слепков: bounded, только известные
    хеши канонов, кастом никогда);
  * ``audit-prompt-matrix.md`` §1–§2, §4 (перечень путей и ≥14 дублей
    «токсичной» персоны), ``evidence/prompt-matrix.json`` (22 пути).

Границы слайса W1 (``plan.md`` §1): реестр + фабричные ревизии + удаление
legacy-речи из effective-слоя + backup. Композер (``services/prompt_composer``)
не переписывается; UI «Речь и характер», редактор стиля и Inspector — W6;
типизированные hard/soft-правила стиля — W3; capability-слой и удаление
жёсткой фразы image-фолбэка из пользовательского пути — W10 (здесь только
регистрация управляемого шаблона с Factory Default).

Провенанс persisted-значений (fix-pass review-w1 BLOCKER-1, §1.2/§4.6/§8):
старое речевое значение из PG («старые PG overrides», включая кастомы) не
является активным слоем само по себе — активным слоем становится текст,
**записанный через API реестра/фабрики** (``prompt_factory.write_speech_value``
/ ``apply_factory_reset``). Класс таких блоков — PG-управляемые речевые каноны
старой личности (``legacy_persona=True`` + ``pg_key``): 11 ключей Direct,
Factcheck, Summary, Search, Checkup, Youtube, Web (ветки режимов исключены
явно — см. ``PROVENANCE_EXEMPT_PREFIXES``). Для них persisted-значение
без записи в журнале провенанса (``character.prompt_history.provenance``)
**не доходит до effective-слоя**: действует заводская редакция, а расхождение
видно как диагностика (``persisted_value_withheld`` + причина) и в
``withheld_values()`` — тихой подмены нет. Значение в PG при этом НЕ
переписывается (backup/provenance сохранены, SOUL-AMD.7.2). Блоки вне этого
класса (машинные стадии, ключи-селекторы режимов/стилей,
``summary_l2_writer``) сохраняют прежнюю семантику.

Что здесь есть:
  * ``BLOCKS`` — машиночитаемая карта ``источник → смысл → потребитель →
    Registry ID → решение о миграции`` по всем путям аудита (PG-ключи каталога
    берутся из ``param_catalog`` — единый источник, без дублей текста);
  * Personality Core (CORE-DOC, SOUL-AMD.1.1): два блока-ПОЛЯ документа
    ``character.core`` — ``core.personality`` (полный авторский текст SOUL-02
    «Речь, юмор и мышление», байт-в-байт первоисточник) и
    ``core.personality.compact`` (ручное сжатие того же характера). Действующую
    редакцию выбирает ``core_selection`` (детерминированно, без LLM; причина —
    из ``CORE_DETAIL_REASONS``), провенанс первоисточника — ``CORE_SOURCE``,
    Inspector-вид — ``core_selection_view``;
  * ``factory_text`` / ``factory_revision`` / ``effective_prompt`` —
    фабричная ревизия против активной (effective) с диагностируемым
    источником (``global|chat|default|code``);
  * ``suppress_legacy_speech`` — детерминированная вычистка известных
    сегментов legacy-личности из ПЕРСИСТЕНТНОГО (PG) значения известного
    канона; см. ниже раздел «Legacy speech suppression»;
  * ``registry_view`` — объединённый вид реестра для UI/PM (W6) и тестов.

Инварианты:
  1. Реестр НЕ хранит свои копии текстов: фабричный текст резолвится из
     ``code_source`` каталога/модуля (Space-of-truth = код-канон), поэтому
     «скрытого дубля» не возникает.
  2. Ни одна ветка не бросает: неизвестный блок/нерезолвящийся источник →
     пустая строка + диагностика (fail-open, паритет остальных слоёв).
  3. Подавление legacy-речи применяется только к значениям, пришедшим из
     ПЕРСИСТЕНТНОГО слоя (``chat``/``global``) и только если байты значения
     совпадают с ИЗВЕСТНЫМ каноном. Кастом владельца не переписывается и не
     редактируется «на лету» — он виден как ``legacy_persona_present``
     (витрина конфликта, W6). ИСКЛЮЧЕНИЕ (FIX-CFG07A-F1, deploy 2.58.101):
     для 7 не-фактчек канонов CFG-07A-2 (``CFG07A_PAYLOAD_CLEAN_KEYS``)
     корпусные legacy-маркеры (07A-1) гасятся и в кастом-значениях —
     на сборке effective-payload, сам текст в PG не меняется.
  4. Кодовый fallback (PG недоступен) остаётся байт-в-байт прежним:
     OFF-паритет W2 (``evidence/direct-runtime-assembly.txt``) сохраняется,
     а нормализация самих фабричных редакций — отдельный шаг JB-3/W2-factory.

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.3.1/3.2/4.1 (soul-1, слайс W1)
"""
from __future__ import annotations

import dataclasses
import hashlib
import logging
import re
from typing import Mapping

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "soul1-w3-1"

#: Документ журнала записей реестра (одна аддитивная JSON-запись bot_settings;
#: владелец записи — ``prompt_factory``). Внутри:
#:   * ``items`` — ревизии (заменённые значения, bounded) для отката;
#:   * ``provenance`` — последняя ревизия блока, записанная API реестра
#:     (провенанс: чем можно доверять как активным слоем).
PROVENANCE_DOC_KEY = "character.prompt_history"
PROVENANCE_MAP_FIELD = "provenance"

#: Виды записей, дающие провенанс (§1.2/§4.6): заводской сброс через API и
#: правка владельца через новый API реестра. Аварийный ``backup_restore``
#: провенанса НЕ даёт: старое значение возвращается как ДАННЫЕ (retrievable),
#: но не как действующий речевой слой (§4.6).
PROVENANCE_WRITE_KINDS = ("owner_edit", "factory_reset")

#: Префикс ревизии: ``fac:<sha256_12>`` — фабричная, ``act:<sha256_12>`` —
#: активная (эффективная) ревизия значения.
FACTORY_PREFIX = "fac:"
ACTIVE_PREFIX = "act:"

#: Ревизии фабричных текстов, объявленных канонами канонов (метки владельца
#: канона). Шаг JB-3/W2-factory обязан бампать метку при правке текста.
FACTORY_REVISION_LABELS: dict[str, str] = {
    # Direct / System2
    # ASAP W1 (22.10.2026, §3.1-3.7 source-2026-10-22.md): фабрики Direct
    # (tool phase/L2 writer) и L1 (секция «ВЫБОР УЧАСТИЯ») переписаны текстами
    # владельца байт-в-байт; прежние байты — PREV_*_W1 слепки + ступени
    # prompt_migrations (ADR-1013-3).
    "direct.base.tool_phase": "direct-toolphase-w1",
    # ASAP 2 (23.10.2026, §4.1/§4.2 asap2 source): канон уточнений вставлен
    # (L1 контракт + правило 5-отсылка; L2 абзацы «КАК ПИСАТЬ»); прежние
    # байты — PREV_DIRECT_L1_PLANNER_W1 / PREV_CHAT_VERBALIZER_W1_31.
    "direct.base.l2_writer": "l2-writer-clar",
    "direct.base.synthesizer": "synthesizer-r1023",
    "direct.base.l1_planner": "l1-planner-clar",
    # Режимы вербализатора (легаси-совместимость)
    "verbilizer.mode.casual": "mode-r1023",
    "verbilizer.mode.serious": "mode-r1023",
    "verbilizer.mode.deep_research": "mode-r1023",
    "verbilizer.mode.default": "mode-r1024",
    # Factcheck / Summary / поиск
    "factcheck.base.single": "factcheck-r1022",
    "factcheck.base.analyst": "factcheck-analyst-r1023-f3",
    # ASAP W1 (P0-F «точечно», SOUL1-CLOSE-R1 04.3): identity-фраза снята
    # с активного вербализатора фактчека; жанровые правила сохранены.
    "factcheck.base.verbalizer": "factcheck-verbalizer-w1",
    # CFG-07A-2 (20.10.2026): каноны НЕ-фактчек маршрутов вычищены
    # (safety-bypass/identity/hostility; ADR-1013-3) — метки бампнуты.
    "summary.base.single": "summary-cfg07a",
    "summary.base.editor": "summary-editor-r1025-hotfix4",
    "summary.base.narrator": "summary-narrator-legfix",
    "summary.base.l1_clusterizer": "summary-l1-clusterizer-asap41",
    "summary.base.l2_writer": "summary-l2-writer-asap41",
    "summary.cover.style": "cover-style-default",
    "summary.cover.style_id": "cover-style-id-default",
    "search.base.system": "search-cfg07a",
    # P0-CHECKUP (24.10.2026, addendum §2): жанровый канон переписан
    # owner-редакцией; «СУТЬ АНАЛИЗА» — дословно.
    "checkup.base.system": "checkup-p0-24-10",
    "youtube.base.system": "youtube-cfg07a",
    "youtube.base.video": "youtube-video-cfg07a",
    "web.base.system": "web-cfg07a",
    "memory.extract": "extract-etl",
    "memory.compress": "compress-canon",
    # Внутренние стадии с собственными версиями канона
    "internal.episodes.extract": "episodes_extract-1",
    "internal.episodes.confirm": "continuation_confirm-1",
    # Внутренние machine-стадии (текст в модуле, версии нет — только sha)
    "internal.dream.distill": "dream-distill",
    "internal.dream.deep_sleep_bridge": "deep-sleep-bridge",
    "internal.dream.persona_evolution": "persona-evolution",
    "internal.lore.init": "lore-init",
    "internal.lore.merge": "lore-merge",
    "internal.lore.story": "lore-story",
    "internal.nostalgia.candidate": "nostalgia",
    "internal.dossier.system": "dossier-system",
    "internal.dossier.layer_a": "dossier-layer-a",
    "internal.dossier.layer_b": "dossier-layer-b",
    "internal.vision.analysis": "vision-analysis",
    "internal.self_reflection": "self-reflection",
    "internal.initiative_observer": "initiative-observer",
    "internal.direct_orchestrator": "direct-orchestrator",
    "internal.anticliche.extract": "anticliche-extract",
    # Слои стиля/идентичности (W2/W3 владельцы)
    "identity.no_ai_disclosure": "no-ai-disclosure",
    "identity.self_model_false_block": "self-model-false-block",
    "identity.character_rules": "character-rules-mca08",
    "style.anti_bot": "anti-bot-r1022",
    "style.asymmetry": "asymmetry-r1022",
    "style.typography": "typography-r1023",
    "style.bot_knowledge": "bot-knowledge-r1021",
    # SOUL-1 (W3): hint Speech Style Policy (SOUL-16.1.2/16.4.1)
    "style.policy.hint": "style-hint-soul16-w3",
    "style.format.plain_html": "format-plain-html",
    "style.format.plain_text": "format-plain-text",
    "style.format.rich": "format-rich",
    "retry.cliche": "retry-cliche-r1022",
    "retry.form_guard": "retry-form-guard-mca08",
    "retry.numeric_claim": "retry-numeric-mca15",
    "response.extent.micro": "extent-r1023",
    "response.extent.compact": "extent-r1023",
    "response.extent.normal": "extent-r1023",
    "response.extent.detailed": "extent-r1023",
    "response.extent.longform": "extent-r1023",
    "response.extent.exhaustive": "extent-r1023",
    # Управляемые пользовательские шаблоны
    "message.image_generation_fallback": "image-fallback-r1023",
    "message.clarify_media_target": "clarify-media-mca23",
    "message.smartmodule.phrases": "smartmodule-phrases-r1021",
    "message.smartmodule.chat_persona": "chat-persona-core-voice",
    # Personality Core (CORE-DOC): первоисточник характера.
    # v3 = ASAP W1 (22.10.2026, §3.2/§3.3 source-2026-10-22.md): фабрика =
    # готовый текст владельца байт-в-байт (без регулирования мата, без
    # SOUL-16-ремарки; токсичность/цинизм/абсурд сохранены как личность).
    # v2 (FIX-CORRECTIVE-FOLLOWUP, мат снят) — PREV_PERSONALITY_CORE_*_V2_TEXT;
    # v1 (авторский SOUL-02) — PREV_PERSONALITY_CORE_*; оба слепка в гварде
    # superseded-core (core_selection) не действуют из PG.
    "core.personality": "asap-core-full-v4",
    "core.personality.compact": "asap-core-compact-v4",
    # SOUL-1 (W4): приёмы Humor Craft, рамка few-shot и классификатор окна
    "humor.craft.common": "humor-craft-guard-h11",
    "humor.technique.absurd_escalation": "humor-technique-w4",
    "humor.technique.literalism": "humor-technique-w4",
    "humor.technique.deadpan": "humor-technique-w4",
    "humor.technique.bureaucratic_logic": "humor-technique-w4",
    "humor.technique.unexpected_analogy": "humor-technique-w4",
    "humor.few_shot.block": "humor-fewshot-w4",
    "experience.humor_window.system": "humor-window-classifier-w4",
    # SOUL-AMD.2.6 (W4): жанровые рамки авторских текстов
    "genre.nostalgia.rules": "genre-nostalgia-w4",
    "genre.dream.rules": "genre-dream-w4",
    "genre.lore.rules": "genre-lore-w4",
    "genre.story.rules": "genre-story-w4",
}


# ═══════════════════════════════════════════════════════════════════════════
# 1. Спецификация блока реестра
# ═══════════════════════════════════════════════════════════════════════════

@dataclasses.dataclass(frozen=True)
class PromptBlockSpec:
    """Одна речевая/поведенческая инструкция реестра (SOUL-AMD.3.2).

    ``pg_key`` — ключ ``bot_settings`` (если блок PG-управляем); ``code_source``
    — ``module.attr`` (+ ``code_index``/``code_call``) для фабричного текста.
    Ровно один из них должен давать текст: реестр не дублирует содержимое.

    ``pg_doc_field`` — блок живёт не скаляром, а ПОЛЕМ JSON-документа по
    ``pg_key`` (Personality Core: ``character.core`` → ``full_text`` /
    ``compact_text``, ``design-source-of-truth`` §2.1). Резолв/запись такого
    блока идут через документ, но фабричная редакция — тот же код-канон.
    """

    block_id: str                  # стабильный ID (никаких автогенераций)
    purpose: str                   # назначение простыми словами
    family: str                    # direct|factcheck|summary|search|style|...
    scope: str                     # global | global_chat | code
    pg_key: str | None
    code_source: str | None
    consumers: tuple[str, ...]     # кто читает (file:line из аудита)
    composition_point: str         # место композиции (слой/профиль/стадия)
    enabled_by: str                # гейт/флаг, если есть (иначе "")
    migration: str                 # factory|managed_message|registered_pending:<lane>
    owner_lane: str                # слайс-владелец дальнейших изменений
    speech: bool                   # True — влияет на речь пользователю
    legacy_persona: bool = False   # несёт старую личность («токсичный бот»)
    ui: str = "catalog"            # catalog|catalog_pending|code_only
    code_index: str | None = None  # индекс в dict-константе (extent-блоки)
    code_call: bool = False        # code_source — функция без аргументов
    code_members: tuple[str, ...] | str | None = None  # "*" — все UPPER-str
    note: str = ""
    pg_doc_field: str = ""         # поле JSON-документа pg_key (Core)


# ── 1.1 PG-управляемые ключи каталога: метаданные по ключу ──────────────────
# Ключи берутся из ``param_catalog`` (категория ``prompts``) — единый источник
# (второй список ключей = «скрытая инструкция»). Здесь только метаданные.
_PG_BLOCK_META: dict[str, dict] = {
    "prompts.direct_chat_system_prompt": dict(
        block_id="direct.base.tool_phase", family="direct",
        purpose="База канала Direct (tool-phase, §3.6): чтение контекста, "
                "достоверность, граница этапа; отношения, инструменты, "
                "анти-галлюцинации, правило полноты. Личность не задаёт.",
        consumers=("direct_chat_service.py:2360", "direct_chat_service.py:4593",
                   "prompt_composer(channel_contract)"),
        composition_point="speech_plain/tool_phase (слой channel_contract)",
        enabled_by="", speech=True, legacy_persona=True, scope="global_chat",
        ui="catalog"),
    "prompts.direct_chat_verbalizer_system_prompt": dict(
        block_id="direct.base.l2_writer", family="direct",
        purpose="Канон L2 Writer/Вербализатора Direct (§3.1): контекст и план "
                "→ готовый ответ; личность/типографика — отдельные слои "
                "(Core/Expression/Style), JSON пользователю не отправляется.",
        consumers=("direct_chat_service.py:4082", "direct_chat_service.py:4311",
                   "direct_chat_service.py:7774"),
        composition_point="speech_plain/l2_writer+system2_stage2 (channel_contract)",
        enabled_by="SMART_VERBALIZER_MODES_ENABLED (OFF → legacy PREV-канон)",
        speech=True, legacy_persona=True, scope="global", ui="catalog"),
    "prompts.direct_chat_synthesizer_system_prompt": dict(
        block_id="direct.base.synthesizer", family="direct",
        purpose="Stage-1 Синтезатора System2: сырые логи инструментов → "
                "строгий JSON-справка (машинная стадия, без Core).",
        consumers=("direct_chat_service.py:4283",),
        composition_point="machine_json/system2_stage1 (channel_contract)",
        enabled_by="", speech=False, scope="global", ui="catalog"),
    "prompts.direct_l1_planner_system_prompt": dict(
        block_id="direct.base.l1_planner", family="direct",
        purpose="L1 Planner Direct/Initiative: JSON-план (action/extent/tone/"
                "tool_policy), плановик НЕ пишет прозу.",
        consumers=("direct_chat_service.py:3709", "direct_chat_service.py:7550"),
        composition_point="machine_json/l1_planner (channel_contract)",
        enabled_by="", speech=False, scope="global", ui="catalog"),
    "prompts.verbilizer_mode_casual": dict(
        block_id="verbilizer.mode.casual", family="direct",
        purpose="Режим CASUAL (легаси-совместимость; длину задаёт extent-блок).",
        consumers=("prompt_style_blocks.py:216",),
        composition_point="speech_plain/l2_writer (mode-блок)",
        enabled_by="SMART_VERBALIZER_MODES_ENABLED",
        speech=True, legacy_persona=False, scope="global", ui="catalog"),
    "prompts.verbilizer_mode_serious": dict(
        block_id="verbilizer.mode.serious", family="direct",
        purpose="Режим SERIOUS: грамотно и по делу (легаси-совместимость).",
        consumers=("prompt_style_blocks.py:216",),
        composition_point="speech_plain/l2_writer (mode-блок)",
        enabled_by="SMART_VERBALIZER_MODES_ENABLED",
        speech=True, scope="global", ui="catalog"),
    "prompts.verbilizer_mode_deep_research": dict(
        block_id="verbilizer.mode.deep_research", family="direct",
        purpose="Режим DEEP_RESEARCH: полный структурированный отчёт.",
        consumers=("prompt_style_blocks.py:216",),
        composition_point="speech_rich/l2_writer (mode+format блоки)",
        enabled_by="SMART_VERBALIZER_MODES_ENABLED",
        speech=True, legacy_persona=True, scope="global", ui="catalog"),
    "prompts.verbilizer_default_mode": dict(
        block_id="verbilizer.mode.default", family="direct",
        purpose="Резервный режим на сбойном пути (Stage-1 не дал "
                "response_mode). Штатный роутинг не перехватывает.",
        consumers=("prompt_style_blocks.py:222",),
        composition_point="speech_plain/l2_writer (fail-safe)",
        enabled_by="", speech=True, scope="global", ui="catalog"),
    "prompts.factcheck_system_prompt": dict(
        block_id="factcheck.base.single", family="factcheck",
        purpose="Одностадийный фактчек (legacy-путь): разбор наброса, "
                "вердикт, пруфы. Публикация — человеческий текст.",
        consumers=("factcheck_service.py:181",),
        composition_point="speech_plain/factcheck_single (channel_contract)",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.factcheck_analyst_system_prompt": dict(
        block_id="factcheck.base.analyst", family="factcheck",
        purpose="Аналитик фактчека (машинная стадия): строгий JSON с "
                "доказательствами и response_mode.",
        consumers=("factcheck_service.py:223",),
        composition_point="machine_json/factcheck_analyst",
        enabled_by="", speech=False, scope="global", ui="catalog"),
    "prompts.factcheck_verbalizer_system_prompt": dict(
        block_id="factcheck.base.verbalizer", family="factcheck",
        purpose="Публичная подача вердикта фактчека по JSON-разбору.",
        consumers=("factcheck_service.py:251", "factcheck_service.py:726"),
        composition_point="speech_plain/factcheck_publication",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.summary_system_prompt": dict(
        block_id="summary.base.single", family="summary",
        purpose="Legacy-саммари одним вызовом (OFF/LEVEL-3): события и "
                "комментарии по истории чата.",
        consumers=("summary_generator.py:987", "summary_generator.py:1599",
                   "summary_generator.py:1752"),
        composition_point="speech_plain|editorial_report/summary_legacy",
        enabled_by="summary mode/level", speech=True, legacy_persona=True,
        scope="global", ui="catalog"),
    "prompts.summary_editor_system_prompt": dict(
        block_id="summary.base.editor", family="summary",
        purpose="Редактор саммари (legacy two-call): правка черновика, "
                "правило маркировки, поле обложки.",
        consumers=("summary_generator.py:3765",),
        composition_point="machine_json/summary_editor",
        enabled_by="summary mode", speech=False, scope="global", ui="catalog"),
    "prompts.summary_narrator_system_prompt": dict(
        block_id="summary.base.narrator", family="summary",
        purpose="Рассказчик саммари (публикация по Markdown-выжимке).",
        consumers=("summary_generator.py:3805",),
        composition_point="speech_plain/summary_narrator",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.summary_l1_clusterizer_system_prompt": dict(
        block_id="summary.base.l1_clusterizer", family="summary",
        purpose="Hybrid Summary L1: кластеризация окна и semantic map "
                "(машинная стадия).",
        consumers=("summary_l1_clusterizer.py:1525",
                   "summary_l1_clusterizer.py:1746"),
        composition_point="machine_json/summary_l1",
        enabled_by="summary hybrid mode", speech=False, scope="global",
        ui="catalog"),
    "prompts.summary_l2_writer_system_prompt": dict(
        block_id="summary.base.l2_writer", family="summary",
        purpose="Hybrid Summary L2: статья по source-window (публикация).",
        consumers=("summary_l2_writer.py:1661",),
        composition_point="speech_rich/summary_l2_writer",
        enabled_by="summary hybrid mode", speech=True, scope="global",
        ui="catalog"),
    "prompts.summary_cover_style": dict(
        block_id="summary.cover.style", family="summary",
        purpose="Стиль обложки статьи (единственный реально per-chat "
                "prompt-ключ по аудиту §1).",
        consumers=("summary_generator.py:4063",),
        composition_point="cover_style/editorial",
        enabled_by="cover job", speech=True, scope="global_chat", ui="catalog"),
    "prompts.summary_cover_style_id": dict(
        block_id="summary.cover.style_id", family="summary",
        purpose="Выбранный профиль обложки (per-chat слот).",
        consumers=("cover_style_pipeline.py:397",
                   "cover_style_pipeline.py:402"),
        composition_point="cover_style/editorial",
        enabled_by="cover job", speech=False, scope="global_chat",
        ui="catalog"),
    "prompts.search_system_prompt": dict(
        block_id="search.base.system", family="search",
        purpose="Веб-исследование по запросу: выжимка по поисковым данным.",
        consumers=("search_service.py:70",),
        composition_point="speech_plain/smartmodule_search",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.checkup_system_prompt": dict(
        block_id="checkup.base.system", family="checkup",
        purpose="Ежемесячный чек-ап: разбор метрик/логов в человеческий отчёт.",
        consumers=("checkup_service.py:47",),
        composition_point="speech_plain/smartmodule_checkup",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.youtube_system_prompt": dict(
        block_id="youtube.base.system", family="youtube",
        purpose="Выжимка видео по расшифровке (пользовательский текст).",
        consumers=("youtube_summarizer_service.py:92",
                   "youtube_summarizer_service.py:139"),
        composition_point="speech_plain/smartmodule_youtube",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.youtube_video_system_prompt": dict(
        block_id="youtube.base.video", family="youtube",
        purpose="Выжимка видео по кадрам/звуку (video-cascade).",
        consumers=("youtube_summarizer_service.py:176",),
        composition_point="speech_plain/smartmodule_youtube_video",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.webpage_system_prompt": dict(
        block_id="web.base.system", family="web",
        purpose="Выжимка веб-страницы по распарсенному тексту.",
        consumers=("web_summarizer_service.py:55",),
        composition_point="speech_plain/smartmodule_webpage",
        enabled_by="", speech=True, legacy_persona=True, scope="global",
        ui="catalog"),
    "prompts.extract_system_prompt": dict(
        block_id="memory.extract", family="memory",
        purpose="ETL-экстрактор фактов в память (машинная стадия, "
                "не user-facing — аудит §1).",
        consumers=("summary_memory.py (EXTRACT_PROMPT)",),
        composition_point="machine_json/memory_extract",
        enabled_by="", speech=False, scope="global", ui="catalog"),
    "prompts.compress_system_prompt": dict(
        block_id="memory.compress", family="memory",
        purpose="Сжатие памяти (машинная стадия).",
        consumers=("summary_memory.py:2706", "memory_maintenance.COMPRESS_PROMPT"),
        composition_point="machine_json/memory_compress",
        enabled_by="", speech=False, scope="global", ui="catalog"),
}

#: Ключи каталога, у которых нет человеческих метаданных выше, НЕ допускаются:
#: тест полноты падает (иначе новый промпт появился бы в PG без реестра).
_PG_META_REQUIRED = True


# ── 1.2 Кодовые блоки (без PG-ключа): регистрация + решение о миграции ───────

def _b(block_id: str, purpose: str, family: str, scope: str,
       code_source: str | None, consumers: tuple[str, ...],
       composition_point: str, *, owner_lane: str, speech: bool,
       migration: str = "registered_pending:W3", legacy_persona: bool = False,
       ui: str = "code_only", enabled_by: str = "", code_index: str | None = None,
       code_call: bool = False, code_members=None,
       note: str = "", pg_key: str | None = None,
       pg_doc_field: str = "") -> PromptBlockSpec:
    return PromptBlockSpec(
        block_id=block_id, purpose=purpose, family=family, scope=scope,
        pg_key=pg_key, code_source=code_source, consumers=consumers,
        composition_point=composition_point, enabled_by=enabled_by,
        migration=migration, owner_lane=owner_lane, speech=speech,
        legacy_persona=legacy_persona, ui=ui, code_index=code_index,
        code_call=code_call, code_members=code_members, note=note,
        pg_doc_field=pg_doc_field)


_CODE_BLOCKS: tuple[PromptBlockSpec, ...] = (
    # ── Personality Core (CORE-DOC, SOUL-02/AMD.1.1): документ владельца ────
    _b("core.personality",
       "Personality Core — ПОЛНАЯ авторская редакция «Речь, юмор и мышление» "
       "(первоисточник владельца): постоянный характер бота, доступен для "
       "правки любым фрагментом.",
       "core", "global_chat",
       "services.chat_prompts.PERSONALITY_CORE_FULL_TEXT",
       ("prompt_composer.py:615", "prompt_factory.py:319",
        "tests/test_soul1_core_doc_text.py"),
       "speech_plain|channel_text_only/core (слой core)",
       owner_lane="W2", speech=True, migration="factory", ui="catalog_pending",
       pg_key="character.core", pg_doc_field="full_text",
       note="Поле full_text JSON-документа `character.core` (design §2.1); "
            "фабричная ревизия байт-в-байт из SOUL-02 (строки 43–53), "
            "провенанс — CORE_SOURCE. Ключ/редактор в каталоге — W6."),
    _b("core.personality.compact",
       "Personality Core, компактная runtime-редакция: тот же характер и те "
       "же запреты ручным сжатием полного текста (экономия контекста).",
       "core", "global_chat",
       "services.chat_prompts.PERSONALITY_CORE_COMPACT_TEXT",
       ("prompt_composer.py:615", "prompt_factory.py:319",
        "tests/test_soul1_core_doc_text.py"),
       "speech_plain|channel_text_only/core (слой core)",
       owner_lane="W2", speech=True, migration="factory", ui="catalog_pending",
       pg_key="character.core", pg_doc_field="compact_text",
       note="Не LLM-пересказ: производная полного текста (см. "
            "PERSONALITY_CORE_COMPACT_DERIVATION); дефолт runtime при "
            "UNIFIED_COMPOSER_ENABLED (виден в манифесте слоя core)."),
    # ── Управляемые пользовательские шаблоны (SOUL-AMD.3.4, §5.3) ──────────
    _b("message.image_generation_fallback",
       "Текст пользователю при провале генерации изображения (реальный код "
       "отказа, без ложного «я не умею»).",
       "message", "code", "services.image_generation.IMAGE_GENERATION_FALLBACK_PHRASE",
       ("tool_router.py:2993", "image_generation.py:1842",
        "tests/test_unified_image_request_round1026.py:361"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       note="W10: из пользовательского пути УБРАНА (SOUL-AMD.5.15) — "
            "действуют шаблоны `message.image_failure.*` по реальному коду "
            "отказа; эта заводская редакция остаётся в реестре как "
            "исторический слепок/аварийный текст (не рендерится)."),
    # ── W10 (SOUL-AMD.5.15/3.4): шаблоны отказа по РЕАЛЬНОМУ коду ───────────
    # Одна фраза «на все случаи» (выше) больше НЕ рендерится в
    # пользовательский путь: заменена управляемыми сообщениями по классу
    # отказа. Каждый блок — отдельная редактируемая PG-ревизия
    # (`content.image_failure.*`, запись через API реестра:
    # `prompt_factory.write_speech_value`, история/откат/Factory Default).
    _b("message.image_failure.disabled",
       "Ответ пользователю, когда генерация изображений выключена "
       "(модуль/лимит-запрет) — честно «выключено», без «я не умею».",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_DISABLED_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "direct_chat_service._image_capability_gate",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.disabled",
       note="Выбирается по статусу capability `disabled` (SOUL-AMD.5.12/5.15)."),
    _b("message.image_failure.not_configured",
       "Ответ пользователю, когда генератор не подключён (нет ключа/модели) — "
       "отличается от выключенного модуля и от временного сбоя.",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_NOT_CONFIGURED_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "direct_chat_service._image_capability_gate",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.not_configured",
       note="Выбирается по статусу `not_configured` и по реальным кодам "
            "`unauthorized`/`forbidden`/`payment_required`."),
    _b("message.image_failure.temporarily_unavailable",
       "Ответ пользователю при временном сбое провайдера (таймаут/сеть/5xx).",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_TEMPORARY_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "capability_registry.record_outcome",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.temporarily_unavailable",
       note="Выбирается по статусу `temporarily_unavailable` и транзиентным "
            "кодам (`timeout`/`network`/`http_5xx`/`rate_limited`)."),
    _b("message.image_failure.quota_exhausted",
       "Ответ пользователю при исчерпанной суточной квоте генерации.",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_QUOTA_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "capability_registry._image_quota",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.quota_exhausted",
       note="Выбирается по статусу `quota_exhausted` и коду `budget` "
            "(§17.2 `financial_limit_reached`)."),
    _b("message.image_failure.unsupported",
       "Ответ пользователю, когда запрос не по части генератора "
       "(слишком большой/невалидный) — без обещаний.",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_UNSUPPORTED_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.unsupported",
       note="Выбирается по статусу `unsupported` и кодам `too_large`/"
            "`empty_prompt`."),
    _b("message.image_failure.unknown",
       "Ответ пользователю при неклассифицированном отказе генерации "
       "(честное «что-то сломалось», без выдуманных причин).",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_UNKNOWN_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.unknown",
       note="Дефолт для нераспознанных кодов отказа (не молчание)."),
    _b("message.image_failure.delivery_failed",
       "Ответ пользователю, когда картинка сгенерирована, но отправка в "
       "Telegram не подтвердилась (успех ≠ доставка).",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_DELIVERY_TEXT",
       ("image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "tests/test_soul1_capability_fallbacks.py"),
       "managed_message/image_failure", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.delivery_failed",
       note="Выбирается по коду `send_failed`/`no_bot` (§17.2 "
            "`delivery_unknown`): «отправил» не заявляется."),
    # CFG-02B (§02B.6): отказ короткой паузы частотного лимита — отдельный
    # редактируемый текст (не «квота» и не «провайдер»); факт-строка с
    # остатком («снова можно через …») добавляется кодом как факт.
    _b("message.image_failure.freq_limited",
       "Ответ пользователю, когда сработал короткий лимит частоты генераций "
       "(слишком много картинок подряд) — честно «пауза», с фактическим "
       "остатком отдельной строкой.",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_FAILURE_FREQ_TEXT",
       ("image_generation.generate_and_send",
        "image_generation.maybe_handle_keyword", "tool_router._generate_image",
        "tests/test_cfg02b_image_freq_limits.py"),
       "managed_message/image_failure", owner_lane="W-CFG-02B", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_failure.freq_limited",
       note="Выбирается по реальному коду `freq_limit`; параметры серии и "
            "режим (per-user/per-chat) — настройки «Лимиты генерации»."),
    _b("message.image_request.clarify",
       "Один короткий уточняющий вопрос, когда поручение изображения "
       "неоднозначно (есть действие, нет объекта/цели).",
       "message", "global_chat",
       "services.chat_prompts.IMAGE_REQUEST_CLARIFY_TEXT",
       ("direct_chat_service._image_capability_gate",
        "tests/test_soul1_capability_intent.py"),
       "managed_message/clarification", owner_lane="W10", speech=True,
       migration="managed_message", ui="catalog_pending",
       pg_key="content.image_request_clarify",
       note="SOUL-AMD.5.9: ровно один вопрос вместо генерации или молчания."),
    _b("message.clarify_media_target",
       "Один короткий уточняющий вопрос для media/transcription без цели.",
       "message", "code", "services.response_extent.CLARIFY_MEDIA_TARGET",
       ("response_extent.clarification_question:591",),
       "managed_message/clarification", owner_lane="W3", speech=True,
       migration="managed_message", ui="catalog_pending"),
    _b("message.checkup_fallback_notice",
       "Фраза-приписка к system-сообщению чек-апа, когда облачное API "
       "мониторинга недоступно (пользователь слышит её в отчёте; несёт "
       "оценочную инструкцию в техническом обработчике).",
       "message", "code", "services.checkup_prompts.CHECKUP_FALLBACK_NOTICE",
       ("checkup_service.py:72", "tests/test_checkup_service.py:55"),
       "managed_message/checkup_fallback", owner_lane="W3", speech=True,
       migration="managed_message", ui="catalog_pending",
       note="SOUL-AMD.3.4: шаблонная фраза, которую слышит пользователь, "
            "обязана быть управляемым Factory Default (как "
            "message.image_generation_fallback); замена текста — W3, "
            "здесь только регистрация + видимость в реестре."),
    _b("message.smartmodule.chat_persona",
       "Самоидентификация в ответе /persona (smartmodule) — голос Core: "
       "прежняя legacy-фраза заменена (SOUL-AMD.4.6(в), FIX-SOUL-F1F3).",
       "message", "code", "services.smartmodule_phrases.CHAT_PERSONA_PHRASE",
       ("handlers/direct_chat.py:59", "handlers/direct_chat.py:253"),
       "managed_message/smartmodule", owner_lane="W3", speech=True,
       migration="managed_message", ui="catalog_pending",
       note="Код-путь (не PG): подавление на сборке не применяется — "
            "фраза заменена на голос Core (FIX-SOUL-F1F3, 18.10.2026); "
            "дальнейшие правки текста — управляемым шаблоном в W3."),
    _b("message.smartmodule.phrases",
       "Семейство шаблонных пользовательских фраз smartmodule (память, "
       "стиль, тон): все UPPER-константы модуля под одним блоком реестра.",
       "message", "code", "services.smartmodule_phrases",
       ("handlers/direct_chat.py:253", "smartmodule_utils.send_text"),
       "managed_message/smartmodule", owner_lane="W3", speech=True,
       migration="managed_message", ui="catalog_pending", code_members="*",
       note="Новая фраза в модуле меняет отпечаток набора и обязана быть "
            "осознанно зарегистрирована (guard SOUL-AMD.3.2)."),
    # ── Идентичность (W2) ──────────────────────────────────────────────────
    _b("identity.no_ai_disclosure",
       "Граница «не раскрывать ИИ» для не-осознанных персон.",
       "identity", "code", "services.bot_persona._NO_AI_DISCLOSURE_BLOCK",
       ("bot_persona.build_persona_prompt_block:312",),
       "speech_plain/identity (слой identity)", owner_lane="W2", speech=True),
    _b("identity.self_model_false_block",
       "Граница «не раскрывать ИИ» при активном кадре SelfModel "
       "(заменяет no_ai_disclosure).",
       "identity", "code", "services.mca_self_model.SELF_MODEL_FALSE_BLOCK",
       ("mca_self_model.render_frame_block:1810",),
       "speech_plain/identity", owner_lane="W2", speech=True),
    _b("identity.character_rules",
       "Правила «мнение vs факт, не выдумывать события» (владелец — данные "
       "персоны, не канон канала).",
       "identity", "code", "services.bot_persona._CHARACTER_RULES_BLOCK",
       ("bot_persona.build_character_rules_block:363",
        "direct_chat_service.py:2402"),
       "speech_plain/identity (слой identity)", owner_lane="W2", speech=True),
    # ── Стиль и защита формы (W3) ──────────────────────────────────────────
    _b("style.anti_bot",
       "Запрет RLHF-тропов и сервисных формул (суффикс всех отвечающих "
       "канонов).",
       "style", "code", "services.prompt_style_blocks.ANTI_BOT_BLOCK",
       ("chat_prompts.py:275", "summary_prompts.py", "factcheck_prompts.py"),
       "channel_contract/suffix", owner_lane="W3", speech=True),
    _b("style.asymmetry",
       "Структурная асимметрия вместо шаблонного ответа.",
       "style", "code", "services.prompt_style_blocks.ASYMMETRY_BLOCK",
       ("chat_prompts.py:275",), "channel_contract/suffix",
       owner_lane="W3", speech=True),
    _b("style.typography",
       "Типографика: короткие дефисы и обычные кавычки (защита Telegram).",
       "style", "code", "services.prompt_style_blocks.TYPOGRAPHY_BLOCK",
       ("chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT:348",),
       "speech_plain/l2_writer (канон)", owner_lane="W3", speech=True),
    _b("style.bot_knowledge",
       "Как использовать <bot_knowledge> в ответе.",
       "style", "code", "services.prompt_style_blocks.BOT_KNOWLEDGE_INSTRUCTION",
       ("factcheck_prompts.py:29", "search_prompts.py:16",
        "summary_prompts.py:29", "web_prompts.py:15"),
       "channel_contract (внутри канонов)", owner_lane="W3", speech=True),
    _b("style.format.plain_html",
       "Канальный формат plain+HTML (Direct deep_research).",
       "style", "code", "services.prompt_style_blocks.FORMAT_PLAIN_BLOCK",
       ("prompt_style_blocks.format_block:256",),
       "channel_output/plain_html", owner_lane="W3", speech=True),
    _b("style.format.plain_text",
       "Канальный формат text-only plain (саммари/фактчек без HTML).",
       "style", "code", "services.prompt_style_blocks.FORMAT_PLAIN_TEXT_BLOCK",
       ("prompt_style_blocks.format_block:256",),
       "channel_output/plain_text", owner_lane="W3", speech=True),
    _b("style.format.rich",
       "Канальный формат rich-статьи (sendRichMessage).",
       "style", "code", "services.prompt_style_blocks.FORMAT_RICH_BLOCK",
       ("prompt_style_blocks.format_block:256",),
       "channel_output/rich", owner_lane="W3", speech=True),
    # ── Speech Style Policy (SOUL-16, W3): короткий hint активных правил ────
    _b("style.policy.hint",
       "Короткий semantic hint Speech Style Policy для Writer (слой 10): "
       "жёсткие правила формы и мягкие привычки письма владельца. НЕ вся база "
       "правил (SOUL-16.4.1).",
       "style", "global_chat", "services.prompt_style_blocks",
       ("prompt_composer.py:1385 (слой style_policy_hint)",
        "style_policy.resolve_style_policy_ref",
        "tests/test_soul1_style_policy.py"),
       "speech_plain/speech_rich (слой style_policy_hint)",
       owner_lane="W3", speech=True, migration="factory",
       ui="catalog_pending", code_members=(
           "STYLE_POLICY_HINT_OPEN", "STYLE_POLICY_HINT_CLOSE",
           "HINT_ONE_WORD", "HINT_MICRO", "HINT_TRAILING_PERIOD_HARD",
           "HINT_TRAILING_PERIOD_SOFT", "HINT_QUOTES_HARD", "HINT_QUOTES_SOFT",
           "HINT_EMOJI_HARD", "HINT_EMOJI_SOFT", "HINT_LINE_BREAKS_PREFIX",
           "HINT_FORBIDDEN_CHARS", "HINT_VERBATIM_PROTECTED",
           "HINT_SOFT_PREFIX"),
       note="Фабричная редакция = тексты hint'а одного модуля; правка любой "
            "формулировки меняет отпечаток набора и требует бампа метки "
            "(SOUL-AMD.3.2). Типизированные правила и документ `style.policy` "
            "— витрина `style_policy_view()` (W3); ключ каталога и редактор — "
            "W6."),
    _b("retry.cliche",
       "Повтор при нарушении Negative Constraints (постпроцессор).",
       "style", "code", "services.prompt_style_blocks.CLICHE_RETRY_SYSTEM_PROMPT",
       ("negative_constraints.py:813", "prompt_style_blocks.py:62"),
       "postprocess/retry", owner_lane="W3", speech=True),
    _b("retry.form_guard",
       "Повтор «только форма» (числа/смысл сохранить).",
       "style", "code",
       "services.prompt_style_blocks.FORM_GUARD_RETRY_SYSTEM_PROMPT",
       ("negative_constraints.py:813",), "postprocess/retry",
       owner_lane="W3", speech=True),
    _b("retry.numeric_claim",
       "Повтор при незаземлённом числе о статистике чата.",
       "style", "code",
       "services.prompt_style_blocks.NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT",
       ("negative_constraints.py", "mca_gates.postprocess_form_guard"),
       "postprocess/retry", owner_lane="W3", speech=True),
    # ── Полнота ответа (W3) ────────────────────────────────────────────────
    _b("response.extent.micro", "Ожидаемая полнота: микро-ответ.",
       "response", "code", "services.response_extent._EXTENT_BLOCKS",
       ("direct_chat_service.py:2692", "prompt_style_blocks.resolve_mode_parts"),
       "speech_plain/response_plan", owner_lane="W3", speech=True,
       code_index="micro"),
    _b("response.extent.compact", "Ожидаемая полнота: компактно.",
       "response", "code", "services.response_extent._EXTENT_BLOCKS",
       ("direct_chat_service.py:2692",), "speech_plain/response_plan",
       owner_lane="W3", speech=True, code_index="compact"),
    _b("response.extent.normal", "Ожидаемая полнота: обычная.",
       "response", "code", "services.response_extent._EXTENT_BLOCKS",
       ("direct_chat_service.py:2692",), "speech_plain/response_plan",
       owner_lane="W3", speech=True, code_index="normal"),
    _b("response.extent.detailed", "Ожидаемая полнота: подробно.",
       "response", "code", "services.response_extent._EXTENT_BLOCKS",
       ("direct_chat_service.py:2692",), "speech_plain/response_plan",
       owner_lane="W3", speech=True, code_index="detailed"),
    _b("response.extent.longform",
       "Ожидаемая полнота: развёрнутый законченный результат.",
       "response", "code", "services.response_extent._EXTENT_BLOCKS",
       ("direct_chat_service.py:2692",), "speech_plain/response_plan",
       owner_lane="W3", speech=True, code_index="longform"),
    _b("response.extent.exhaustive", "Ожидаемая полнота: исчерпывающе.",
       "response", "code", "services.response_extent._EXTENT_BLOCKS",
       ("direct_chat_service.py:2692",), "speech_plain/response_plan",
       owner_lane="W3", speech=True, code_index="exhaustive"),
    # ── W4 (SOUL-06/07/08): Humor Craft, Few-Shot и классификатор окна ──────
    # Приёмы юмора — управляемый ситуационный слой (не личность): заводские
    # редакции живут в модуле-владельце, здесь только регистрация + ID.
    _b("humor.craft.common",
       "Общая рамка Humor Craft: главный критерий — причинная связность и "
       "уместность (не частота мата/метафор/оскорблений), запрет повторяемых "
       "зачинов/финалов, неприкосновенность фактов и сути просьбы (SOUL-06.6).",
       "humor", "code", "services.mca_humor_craft.HUMOR_CRAFT_GUARD",
       ("prompt_composer.py:1309 (слой humor_craft)",
        "mca_humor_craft.render_layer"),
       "speech_plain|speech_rich/humor_craft (слой 8)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending",
       note="Владелец выключает ремесло документом `humor.craft` (enabled) и "
            "осью `flags.humor_craft_enabled`; Core при этом жив (SOUL-06.7)."),
    _b("humor.technique.absurd_escalation",
       "Приём «абсурдная эскалация» (SOUL-06.1): предпосылка как правило мира, "
       "развитие следствий, неожиданный логичный вывод.",
       "humor", "code",
       "services.mca_humor_craft.HUMOR_TECHNIQUE_ABSURD_ESCALATION",
       ("mca_humor_craft.TECHNIQUE_TEXTS",),
       "speech_plain/humor_craft (по comic_strategy L1)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending"),
    _b("humor.technique.literalism",
       "Приём «буквализм» (SOUL-06.2): метафора/оговорка понята буквально, "
       "комическая закономерность следует из буквального прочтения.",
       "humor", "code",
       "services.mca_humor_craft.HUMOR_TECHNIQUE_LITERALISM",
       ("mca_humor_craft.TECHNIQUE_TEXTS",),
       "speech_plain/humor_craft (по comic_strategy L1)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending"),
    _b("humor.technique.deadpan",
       "Приём «сухой deadpan» (SOUL-06.3): нелепое утверждение как обыденный "
       "факт, без эмоциональной подачи.",
       "humor", "code", "services.mca_humor_craft.HUMOR_TECHNIQUE_DEADPAN",
       ("mca_humor_craft.TECHNIQUE_TEXTS",),
       "speech_plain/humor_craft (по comic_strategy L1)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending"),
    _b("humor.technique.bureaucratic_logic",
       "Приём «бюрократический/экономический перенос» (SOUL-06.4): быт как "
       "процесс/отчёт/регламент/налог/сделка, без однообразного ведомства.",
       "humor", "code",
       "services.mca_humor_craft.HUMOR_TECHNIQUE_BUREAUCRATIC_LOGIC",
       ("mca_humor_craft.TECHNIQUE_TEXTS",),
       "speech_plain/humor_craft (по comic_strategy L1)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending"),
    _b("humor.technique.unexpected_analogy",
       "Приём «неожиданная, но содержательная аналогия» (SOUL-06.5): "
       "отдалённая область с конкретными деталями и внутренней логикой.",
       "humor", "code",
       "services.mca_humor_craft.HUMOR_TECHNIQUE_UNEXPECTED_ANALOGY",
       ("mca_humor_craft.TECHNIQUE_TEXTS",),
       "speech_plain/humor_craft (по comic_strategy L1)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending"),
    _b("humor.few_shot.block",
       "Рамка few-shot блока (SOUL-07.2): примеры задают механизм мышления, "
       "а не готовые фразы; запрет дословного копирования лексики и чужих "
       "реалий.",
       "humor", "code",
       "services.mca_sample_library.HUMOR_FEW_SHOT_TEMPLATE",
       ("mca_sample_library.render_block",
        "prompt_composer.py:1346 (слой few_shot)"),
       "speech_plain|speech_rich/few_shot (слой 9)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending",
       note="Само содержимое библиотеки — таблица `humor_samples` (не промпт); "
            "владелец одобряет эталоны в разделе «Примеры». Заводская редакция "
            "— единый шаблон `HUMOR_FEW_SHOT_TEMPLATE` (открытие/строка/"
            "закрытие) в модуле-владельце."),
    _b("experience.humor_window.system",
       "Классификатор реакций на шутку (машинная стадия окна после ответа): "
       "строгий JSON-сигнал с уверенностью и evidence, без выдумывания данных.",
       "experience", "code",
       "services.mca_humor_feedback.HUMOR_WINDOW_SYSTEM_PROMPT",
       ("mca_humor_feedback.classify_rows",
        "mca_experience_jobs.ExperienceReviewRunner.run"),
       "machine/humor_window (внутренняя стадия Experience)",
       owner_lane="W4", speech=False, migration="factory", ui="code_only",
       note="Человекопонятного вывода не создаёт: только типизированный "
            "сигнал для контура опыта (SOUL-08.8)."),
    # ── W4 (SOUL-AMD.2.6): жанровые рамки авторских текстов ────────────────
    # Сны/ностальгия/лор/истории — публичная речь бота: получают Core и
    # жанровые правила (уточнение §2.1), а не служебный нейтральный текст.
    _b("genre.nostalgia.rules",
       "Жанровая рамка «Ностальгия»: живой голос воспоминания, без выдуманных "
       "событий/дат; служебное слово отказа канона сохраняется.",
       "genre", "code", "services.mca_authorial_speech.GENRE_NOSTALGIA_RULES",
       ("mca_authorial_speech.genre_base_prompt",
        "nostalgia_worker._llm_once"),
       "speech_plain/nostalgia_writer (жанровая рамка в base)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending"),
    _b("genre.dream.rules",
       "Жанровая рамка «Сон»: связная история голосом бота, не отчёт о "
       "данных и не выдуманные события чата.",
       "genre", "code", "services.mca_authorial_speech.GENRE_DREAM_RULES",
       ("mca_authorial_speech.genre_base_prompt",),
       "speech_plain/dream_writer (жанровая рамка в base)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending",
       note="AMD26: сны и глубокий сон в продукте — внутренние машинные "
            "стадии (§2.2, без Core), публикующего пути «рассказ о сне» нет; "
            "рамка зарегистрирована как Factory Default и готова, когда "
            "такой путь появится (собирается через `authorial_system`)."),
    _b("genre.lore.rules",
       "Жанровая рамка «Лор»: история чата своим голосом на проверенных "
       "данных, без нейтрального пересказа и вымысла.",
       "genre", "code", "services.mca_authorial_speech.GENRE_LORE_RULES",
       ("mca_authorial_speech.genre_base_prompt",
        "lore_compiler_service.LoreCompilerService.compile"),
       "speech_plain/lore_writer (жанровая рамка в base)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending",
       note="AMD26: проведена на пути «Летописец» (рассказ о лоре — "
            "публикация в чат safe-HTML, writer `lore_writer`): композер ON "
            "→ Core + рамка, OFF → прежний канон байт-в-байт (паритет). "
            "Генерация авто-лора (`internal.lore.init/merge`) — внутренняя "
            "машинная стадия (§2.2), рамку не получает."),
    _b("genre.story.rules",
       "Жанровая рамка «История/творческий текст»: внутренняя логика и "
       "детали, без подмены фактов вымыслом.",
       "genre", "code", "services.mca_authorial_speech.GENRE_STORY_RULES",
       ("mca_authorial_speech.genre_base_prompt",),
       "speech_plain/story_writer (жанровая рамка в base)",
       owner_lane="W4", speech=True, migration="factory",
       ui="catalog_pending",
       note="AMD26: у продукта нет отдельного публикующего пути «творческий "
            "текст» с собственным каноном (творческие тексты Direct идут "
            "через Core канала Direct, AMD.2.3) — рамка зарегистрирована и "
            "готова для будущего пути через `authorial_system`."),
    # ── Авторские тексты вне каталога (аудит §1: «вне каталога») ───────────
    _b("internal.dream.distill",
       "Дистилляция снов (ночной worker) — авторский текст, но без Core "
       "в канале.",
       "internal", "code", "services.dream_prompts.DREAM_DISTILL_PROMPT",
       ("dream_worker.py:1327",), "internal/dream_distill",
       owner_lane="W4", speech=False,
       note="AMD26: внутренняя машинная стадия (§2.2, без Core) — пишет "
            "убеждения в память; публикующего пути «рассказ о сне» у "
            "продукта нет (рамка `genre.dream.rules` готова для него)."),
    _b("internal.dream.deep_sleep_bridge",
       "Мост глубокого сна (связка событий) — внутренняя стадия.",
       "internal", "code",
       "services.dream_prompts.DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT",
       ("dream_worker.py:2297",), "internal/deep_sleep_bridge",
       owner_lane="W4", speech=False),
    _b("internal.dream.persona_evolution",
       "Эволюция персоны во сне — conflict-surface с Personality Core "
       "(аудит §4.7): не должна тайно переписывать владельческий Core.",
       "internal", "code", "services.dream_prompts.PERSONA_EVOLUTION_PROMPT",
       ("dream_worker.py:2778",), "internal/persona_evolution",
       owner_lane="W4", speech=False,
       note="SOUL-AMD.1.5: динамические черты влияют на проявление, "
            "но не переписывают Core."),
    _b("internal.lore.init", "Инициализация лора (машинная стадия).",
       "internal", "code", "services.lore_prompts.LORE_INIT_SYSTEM_PROMPT",
       ("lore_worker.py:696",), "internal/lore_init", owner_lane="W4",
       speech=False),
    _b("internal.lore.merge", "Слияние записей лора (машинная стадия).",
       "internal", "code", "services.lore_prompts.LORE_MERGE_SYSTEM_PROMPT",
       ("lore_worker.py:692",), "internal/lore_merge", owner_lane="W4",
       speech=False),
    _b("internal.lore.story",
       "Рассказ о лоре — авторский текст, идущий в safe-HTML путь Direct.",
       "internal", "code", "services.lore_prompts.LORE_STORY_SYSTEM_PROMPT",
       ("lore_compiler_service.py:190", "tool_router.py:2827",
        "mca_authorial_speech.authorial_system"),
       "internal/lore_story", owner_lane="W4",
       speech=True,
       note="AMD26: публикующий путь проведён через общий композер "
            "(writer `lore_writer`, жанр `lore`): ON → Core + жанровая рамка, "
            "OFF → канон байт-в-байт; канон остаётся функциональной базой "
            "(HTML/UPD/факты из данных)."),
    _b("internal.nostalgia.candidate",
       "Кандидат ностальгии (cron) — текст уходит в чат через Initiative.",
       "internal", "code", "services.nostalgia_prompts.NOSTALGIA_PROMPT",
       ("nostalgia_worker.py:744",), "internal/nostalgia",
       owner_lane="W4", speech=True),
    _b("internal.dossier.system", "Досье на участника (machine-стадия).",
       "internal", "code", "services.dossier_prompts.DOSSIER_SYSTEM_PROMPT",
       ("lore_worker.py:834",), "internal/dossier_system", owner_lane="W4",
       speech=False),
    _b("internal.dossier.layer_a", "Досье: слой A (сбор entity-фактов).",
       "internal", "code", "services.dossier_prompts.LAYER_A_SYSTEM_PROMPT",
       ("lore_worker.py:798",), "internal/dossier_layer_a", owner_lane="W4",
       speech=False),
    _b("internal.dossier.layer_b", "Досье: слой B (синтез person_fact).",
       "internal", "code", "services.dossier_prompts.LAYER_B_SYSTEM_PROMPT",
       ("lore_worker.py:882",), "internal/dossier_layer_b", owner_lane="W4",
       speech=False),
    _b("internal.episodes.extract",
       "Извлечение эпизодов из окна чата (машинная стадия, JSON).",
       "internal", "code",
       "services.mca_episode_prompts.build_extract_system",
       ("mca_episodes.py:2062", "mca_episodes.py:2192"),
       "internal/episodes_extract", owner_lane="W4", speech=False,
       code_call=True),
    _b("internal.episodes.confirm",
       "Подтверждение продолжения истории (machine-стадия, JSON).",
       "internal", "code",
       "services.mca_episode_prompts.build_confirm_system",
       ("mca_episodes.py:1834", "mca_episodes.py:2269"),
       "internal/continuation_confirm", owner_lane="W4", speech=False,
       code_call=True),
    _b("internal.vision.analysis",
       "Разбор изображения (vision) — внутренние данные, без стиля.",
       "internal", "code", "services.mca_vision.ANALYSIS_SYSTEM_PROMPT",
       ("mca_vision.py:906",), "internal/vision_analysis", owner_lane="W2",
       speech=False),
    _b("internal.self_reflection",
       "Саморефлексия/пересборка SelfModel (внутренняя стадия).",
       "internal", "code", "services.self_reflection.SELF_REFLECTION_PROMPT",
       ("self_reflection.py:108",), "internal/self_reflection",
       owner_lane="W2", speech=False),
    _b("internal.initiative_observer",
       "Оценка ценности инициативного повода (funnel-стадия).",
       "internal", "code",
       "services.initiative_observer.OBSERVER_EVAL_SYSTEM_PROMPT",
       ("initiative_observer.py:895",), "internal/initiative_observer",
       owner_lane="W5", speech=False),
    _b("internal.direct_orchestrator",
       "Tool Orchestrator Direct: выбор инструментов (машинная стадия).",
       "internal", "code",
       "services.direct_execution.ORCHESTRATOR_SYSTEM_PROMPT",
       ("direct_execution.py:641",), "internal/tool_orchestrator",
       owner_lane="W10", speech=False),
    _b("internal.anticliche.extract",
       "Извлечение анти-клише (worker) — правила формы, не личность.",
       "internal", "code", "services.anticliche_worker.EXTRACT_SYSTEM_PROMPT",
       ("anticliche_worker.py:150",), "internal/anticliche_extract",
       owner_lane="W3", speech=False),
)


# ═══════════════════════════════════════════════════════════════════════════
# 1.3 Personality Core (CORE-DOC): документ характера и выбор редакции
# ═══════════════════════════════════════════════════════════════════════════
# Один JSON-документ на scope (``design-source-of-truth`` §2.1): глобальный —
# ``bot_settings('character.core')``, per-chat — ``chat_params.overrides``
# того же ключа. Два ПОЛЯ документа = два зарегистрированных блока выше
# (``full_text`` / ``compact_text``); ``detail_level`` выбирает действующую
# редакцию, ``revision`` — версия документа (история/откат — prompt_factory).

CORE_DOC_KEY = "character.core"
CORE_FULL_BLOCK_ID = "core.personality"
CORE_COMPACT_BLOCK_ID = "core.personality.compact"
CORE_DETAIL_LEVELS = frozenset({"compact", "full"})
CORE_FIELD_BY_LEVEL = {"compact": "compact_text", "full": "full_text"}

#: Закрытый набор причин выбора редакции Core (виден в манифесте слоя core и
#: в Inspector-виде): «почему ушла именно эта редакция».
CORE_DETAIL_REASONS = frozenset({
    "factory_default",       # документа владельца нет — действует заводская
    "document_default",      # документ есть, detail_level владелец не выбирал
    "owner_setting",         # выбор владельца (detail_level документа)
    "full_text_missing",     # полной редакции нет → компактная
    "compact_text_missing",  # компактной редакции нет → полная
})

#: Провенанс первоисточника полной редакции. ИСТОРИЯ:
#:   * v1 — авторский SOUL-02 «Речь, юмор и мышление»
#:     (plans/features/soul-1/source-current-task.md, строки 43–53; провенанс
#:     в CORE_SOURCE_V1);
#:   * v2 — FIX-CORRECTIVE-FOLLOWUP (21.10.2026): мат-тема снята
#:     (PREV_PERSONALITY_CORE_FULL_V2_TEXT, прод-байты 2.58.110
#:     d98e72ec7926);
#:   * v3 (ТЕКУЩАЯ) — ASAP W1 (22.10.2026, §3.2 source-2026-10-22.md):
#:     готовый текст владельца байт-в-байт; сверка байтов —
#:     tests/test_asap_w1_semantics.py (fence §3.2 == константа).
CORE_SOURCE_V1: dict = {
    "path": "plans/features/soul-1/source-current-task.md",
    "chapter": "§3 SOUL-02 — Единый Personality Core как собственность владельца",
    "heading": "### Речь, юмор и мышление",
    "line_start": 43,
    "line_end": 53,
    "req_ids": ("SOUL-02.1", "SOUL-02.2", "SOUL-02.3", "SOUL-02.4",
                "SOUL-02.5", "SOUL-02.6"),
    "map": "plans/features/soul-1/requirements-map.json",
    "amendment": "SOUL-AMD.1.1 + FIX-CORRECTIVE-FOLLOWUP 21.10.2026 §1",
    "note": "исторический провенанс v1/v2; фабрика v3 — CORE_SOURCE",
}

CORE_SOURCE: dict = {
    "path": "plans/features/asap-speech-arch/source-2026-10-22.md",
    "chapter": "§3.2 P0-B — Core Full / core.personality (готовый текст владельца)",
    "heading": "### 3.2. P0-B",
    "factory_rev_label": FACTORY_REVISION_LABELS[CORE_FULL_BLOCK_ID],
    "compact_factory_rev_label": FACTORY_REVISION_LABELS[
        CORE_COMPACT_BLOCK_ID],
    "history": (CORE_SOURCE_V1, "v2=PREV_PERSONALITY_CORE_*_V2_TEXT "
                "(FIX-CORRECTIVE-FOLLOWUP, прод 2.58.110)"),
}


def _token_estimate(text: str) -> int:
    """Тот же оценщик, что ``prompt_composer.estimate_tokens`` (4 симв. ≈ токен)."""
    return max(1, (len(str(text or "")) + 3) // 4)


def doc_field_text(doc, field: str) -> str:
    """Текст поля JSON-документа ("" — поля нет, пусто или это не документ)."""
    if not isinstance(doc, Mapping):
        return ""
    value = doc.get(field)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:      # pragma: no cover — битые байты
            return ""
    return value if isinstance(value, str) else ""


#: Ленивый кэш sha12 ПРЕЖНИХ заводских Core-редакций (гвард superseded-core,
#: см. core_selection; импорт chat_prompts ленивый — без цикла).
#: ASAP W1: прежних редакций ДВЕ — v1 (авторский SOUL-02 с мат-темой) и
#: v2 (FIX-CORRECTIVE-FOLLOWUP, прод-байты 2.58.110); обе не действуют из PG,
#: кастом владельца (в т.ч. его ручная правка 22.10) не подменяется.
_SUPERSEDED_CORE_SHA_CACHE: dict[str, frozenset] = {}


def _superseded_core_shas() -> tuple[frozenset, frozenset]:
    """(множество sha12 прежних полных, множество прежних компактных)."""
    if not _SUPERSEDED_CORE_SHA_CACHE:
        from services.chat_prompts import (
            PREV_PERSONALITY_CORE_COMPACT_TEXT,
            PREV_PERSONALITY_CORE_COMPACT_V2_TEXT,
            PREV_PERSONALITY_CORE_FULL_TEXT,
            PREV_PERSONALITY_CORE_FULL_V2_TEXT,
        )
        _SUPERSEDED_CORE_SHA_CACHE["full"] = frozenset({
            sha12(PREV_PERSONALITY_CORE_FULL_TEXT),
            sha12(PREV_PERSONALITY_CORE_FULL_V2_TEXT),
        })
        _SUPERSEDED_CORE_SHA_CACHE["compact"] = frozenset({
            sha12(PREV_PERSONALITY_CORE_COMPACT_TEXT),
            sha12(PREV_PERSONALITY_CORE_COMPACT_V2_TEXT),
        })
    return (_SUPERSEDED_CORE_SHA_CACHE["full"],
            _SUPERSEDED_CORE_SHA_CACHE["compact"])


def core_selection(doc=None, *, source: str = "default") -> dict:
    """Детерминированный выбор редакции Core: полная/компактная + причина.

    Здесь НЕТ и не может быть LLM: выбор — чистая функция от документа
    владельца и заводских редакций (SOUL-02: «вручную согласованная, а не
    нестабильное LLM-пересказывание»). Правила:

    * пустое поле документа наследует ЗАВОДСКУЮ редакцию этого поля —
      правка одного поля не обнуляет второе;
    * ``detail_level`` документа — выбор владельца (``owner_setting``); без
      него действует заводской дефолт ``compact`` (``factory_default`` /
      ``document_default``);
    * запрошенной редакции нет → берётся другая, причина ``*_text_missing``.

    QUOTA-REMOVAL (ADDENDUM #3 §2.7, A4): принудительное понижение
    ``full → compact`` по локальному бюджету слоёв удалено — выбор владельца
    не подменяется. Реальный размер окна модели учитывается на стороне
    вызова (``model_capacity``), а не квотой на инструкцию.

    Возвращает тексты обеих редакций (для композера) и провенанс выбора.
    """
    factory_full = factory_text(CORE_FULL_BLOCK_ID)
    factory_compact = factory_text(CORE_COMPACT_BLOCK_ID)
    document = doc if isinstance(doc, Mapping) else None
    superseded_fields: list[str] = []
    if document is None:
        full_text, compact_text = factory_full, factory_compact
        origin, revision = "factory", ""
        raw_level = ""
    else:
        full_text = doc_field_text(document, "full_text") or factory_full
        compact_text = doc_field_text(document, "compact_text") or \
            factory_compact
        # CORRECTIVE-FOLLOWUP (21.10.2026, §1) + ASAP W1 (22.10.2026, §3.2):
        # гвард superseded-core. Поле документа, байт-в-байт равное ЛЮБОЙ
        # ПРЕЖНЕЙ заводской редакции Core (v1 с мат-темой / v2 прод-байты
        # 2.58.110), не действует: состоянием остаётся документ (данные не
        # трогаются), а действующим слоем — НОВАЯ заводская редакция v3
        # (прецедент withheld_factory_governs). Кастом владельца (байты не
        # равны известным слепкам) не подменяется никогда.
        _sup_full_shas, _sup_compact_shas = _superseded_core_shas()
        if full_text and sha12(full_text) in _sup_full_shas:
            full_text = factory_full
            superseded_fields.append("full_text")
        if compact_text and sha12(compact_text) in _sup_compact_shas:
            compact_text = factory_compact
            superseded_fields.append("compact_text")
        origin = str(document.get("origin") or "owner_edit")
        revision = str(document.get("revision") or "")
        raw_level = str(document.get("detail_level") or "").strip().lower()
    explicit = raw_level in CORE_DETAIL_LEVELS
    level = raw_level if explicit else "compact"
    reason = ("owner_setting" if explicit else
              ("factory_default" if document is None else "document_default"))
    if level == "full":
        if not full_text.strip():
            level, reason = "compact", "full_text_missing"
    elif not compact_text.strip():
        level, reason = "full", "compact_text_missing"
    text = full_text if level == "full" else compact_text
    active_field = CORE_FIELD_BY_LEVEL[level]
    active_from_owner = bool(document is not None
                             and doc_field_text(document, active_field).strip()
                             and active_field not in superseded_fields)
    return {
        "level": level,
        "reason": reason,
        "text": text,
        "full_text": full_text,
        "compact_text": compact_text,
        "source": str(source or "default"),
        "origin": origin,
        "document_revision": revision,
        "requested_level": raw_level or "compact",
        "active_field": active_field,
        "active_from_owner": active_from_owner,
        "superseded_fields": tuple(superseded_fields),
        "compact_words": (len(compact_text.split()) if compact_text else 0),
        "revision": core_active_revision(text=text, document_revision=revision),
    }


def core_active_revision(*, text: str, document_revision: str = "") -> str:
    """Ревизия действующей редакции Core: ``r<doc>.<sha12>`` | ``fac:<sha12>``.

    Формат ``r<revision>.<sha12>`` сохранён от W2 (hot-apply тесты): правка
    документа меняет и номер, и хеш текста. Для заводской редакции (документа
    нет) используется префикс фабрики ``fac:`` — видно, что действует заводское.
    """
    text = str(text or "")
    if not text:
        return ""
    rev = str(document_revision or "")
    if not rev:
        return FACTORY_PREFIX + sha12(text)
    return f"r{rev}.{sha12(text)}"


def core_selection_view(doc=None, *, source: str = "default") -> dict:
    """Inspector-вид выбора Core: какая редакция действует и почему.

    Без сырых текстов (R17-safe): ревизии/хеши/размеры + провенанс + источник
    каждой редакции (владелец или заводская).

    Аддитивного бюджета инструкций больше нет (ADDENDUM #3 §2.7): локальная
    квота не понижает `full` до `compact`, поэтому параметра бюджета нет и в
    сигнатуре — значение не могло влиять на выбор.
    """
    sel = core_selection(doc, source=source)
    document = doc if isinstance(doc, Mapping) else None

    def _field_view(field: str, text: str) -> dict:
        owner_text = doc_field_text(document, field)
        return {
            "chars": len(text),
            "words": len(text.split()) if text else 0,
            "tokens": _token_estimate(text) if text else 0,
            "sha256_12": sha12(text) if text else "",
            "origin": "owner" if owner_text.strip() else "factory",
        }

    return {
        "doc_key": CORE_DOC_KEY,
        "present": document is not None,
        "level": sel["level"],
        "reason": sel["reason"],
        "requested_level": sel["requested_level"],
        "source": sel["source"],
        "origin": sel["origin"],
        "document_revision": sel["document_revision"],
        "active_revision": sel["revision"],
        "active_field": sel["active_field"],
        "active_from_owner": sel["active_from_owner"],
        "superseded_fields": list(sel.get("superseded_fields") or ()),
        "full": _field_view("full_text", sel["full_text"]),
        "compact": _field_view("compact_text", sel["compact_text"]),
        "factory_revisions": {
            "full": factory_revision(CORE_FULL_BLOCK_ID),
            "compact": factory_revision(CORE_COMPACT_BLOCK_ID),
        },
        "source_provenance": dict(CORE_SOURCE),
        "edit_blocks": {"full": CORE_FULL_BLOCK_ID,
                        "compact": CORE_COMPACT_BLOCK_ID},
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. Сборка реестра (PG-ключи берутся из каталога — единый источник)
# ═══════════════════════════════════════════════════════════════════════════

def _catalog_prompt_specs() -> list:
    """``prompts.*``-спеки каталога (единственный источник списка ключей)."""
    from services import param_catalog as pc
    return [spec for spec in pc.REGISTRY.values()
            if spec.category == pc.CATEGORY_PROMPTS]


def _pg_blocks() -> tuple[PromptBlockSpec, ...]:
    out: list[PromptBlockSpec] = []
    for spec in _catalog_prompt_specs():
        meta = _PG_BLOCK_META.get(spec.pg_key)
        if meta is None:
            # Ключ есть в каталоге, но не описан в реестре: НЕ прячем —
            # отдаём минимальный блок с явной пометкой (тест полноты падает).
            logger.warning("[prompt_registry] ключ каталога вне реестра | %s",
                           spec.pg_key)
            meta = dict(
                block_id="unregistered:" + spec.pg_key, family="unregistered",
                purpose="НЕ ОПИСАН в реестре (требуется метадата W1)",
                consumers=("unknown",), composition_point="unknown",
                enabled_by="", speech=True, scope="global",
                ui="catalog", legacy_persona=False)
        out.append(PromptBlockSpec(
            block_id=meta["block_id"], purpose=meta["purpose"],
            family=meta["family"], scope=meta.get("scope", "global"),
            pg_key=spec.pg_key, code_source=spec.code_source,
            consumers=tuple(meta["consumers"]),
            composition_point=meta["composition_point"],
            enabled_by=meta.get("enabled_by", ""),
            migration="factory", owner_lane=meta.get("owner_lane", "W2"),
            speech=bool(meta.get("speech", True)),
            legacy_persona=bool(meta.get("legacy_persona", False)),
            ui=meta.get("ui", "catalog"), note=meta.get("note", "")))
    return tuple(out)


_BLOCKS_CACHE: tuple[PromptBlockSpec, ...] | None = None


def all_blocks() -> tuple[PromptBlockSpec, ...]:
    """Все блоки реестра (PG + кодовые). Кэш на процесс."""
    global _BLOCKS_CACHE
    if _BLOCKS_CACHE is None:
        try:
            pg = _pg_blocks()
        except Exception:      # pragma: no cover — каталог не должен ронять
            logger.warning("[prompt_registry] каталог недоступен", exc_info=True)
            pg = ()
        _BLOCKS_CACHE = pg + _CODE_BLOCKS
    return _BLOCKS_CACHE


def reset_cache() -> None:
    """Сброс кэша реестра/фабричных текстов (тесты, hot-reload)."""
    global _BLOCKS_CACHE
    _BLOCKS_CACHE = None
    _BY_ID.clear()
    _BY_KEY.clear()
    _FACTORY_TEXTS.clear()
    _KNOWN_CANON_HASHES.clear()


_BY_ID: dict[str, PromptBlockSpec] = {}
_BY_KEY: dict[str, PromptBlockSpec] = {}


def _index() -> None:
    if _BY_ID:
        return
    for spec in all_blocks():
        _BY_ID.setdefault(spec.block_id, spec)
        if spec.pg_key:
            _BY_KEY.setdefault(spec.pg_key, spec)


def block(block_id: str) -> PromptBlockSpec | None:
    _index()
    return _BY_ID.get(block_id)


def by_pg_key(pg_key: str) -> PromptBlockSpec | None:
    _index()
    return _BY_KEY.get(pg_key)


def block_for(pg_key_or_id: str) -> PromptBlockSpec | None:
    """Блок по ID или по PG-ключу (единый вход для вызывающих)."""
    return block(pg_key_or_id) or by_pg_key(pg_key_or_id)


def speech_blocks() -> tuple[PromptBlockSpec, ...]:
    return tuple(b for b in all_blocks() if b.speech)


def legacy_persona_blocks() -> tuple[PromptBlockSpec, ...]:
    return tuple(b for b in all_blocks() if b.legacy_persona)


def unregistered_catalog_keys() -> tuple[str, ...]:
    """PG-ключи каталога без человеческой метадаты реестра (должно быть пусто)."""
    return tuple(spec.pg_key for spec in _catalog_prompt_specs()
                 if spec.pg_key not in _PG_BLOCK_META)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Фабричные ревизии (SOUL-AMD.4.1: версионированные заводские редакции)
# ═══════════════════════════════════════════════════════════════════════════

def sha12(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


_FACTORY_TEXTS: dict[str, str] = {}


def factory_text(block_id: str) -> str:
    """Фабричный текст блока (единый источник — код-канон, без дубля)."""
    if block_id in _FACTORY_TEXTS:
        return _FACTORY_TEXTS[block_id]
    spec = block(block_id)
    text = ""
    if spec is not None and spec.code_source:
        try:
            from services.pg_db import resolve_code_source
            value = resolve_code_source(spec.code_source)
            if spec.code_call and callable(value):
                value = value()
            if spec.code_members:
                value = _members_text(value, spec.code_members)
            elif spec.code_index:
                value = (value or {}).get(spec.code_index, "")
            if isinstance(value, str):
                text = value
        except Exception:
            logger.warning("[prompt_registry] фабричный текст не резолвится | "
                           "block=%s | source=%s", block_id, spec.code_source,
                           exc_info=True)
            text = ""
    _FACTORY_TEXTS[block_id] = text
    return text


def _members_text(module, members) -> str:
    """Собрать фабричный текст семейства констант модуля (для fingerprint).

    ``members == "*"`` — все модульные UPPER-константы-строки: добавление
    новой фразы меняет отпечаток набора и заставляет явно зарегистрировать
    правку (guard SOUL-AMD.3.2), а не «просочиться» в пользовательский путь.
    """
    names = (sorted(attr for attr in dir(module)
                    if attr.isupper()
                    and isinstance(getattr(module, attr), str))
             if members == "*" else list(members))
    rows = []
    for name in names:
        value = getattr(module, name, None)
        if isinstance(value, str):
            rows.append(f"{name}={value}")
    return "\n".join(rows)


def factory_default(block_id: str) -> str:
    """Заводской текст блока (синоним ``factory_text`` для Factory Defaults)."""
    return factory_text(block_id)


def factory_revision(block_id: str) -> str:
    """Ревизия заводской редакции: ``fac:<sha256_12>`` (+ метка владельца)."""
    text = factory_text(block_id)
    if not text:
        return ""
    label = FACTORY_REVISION_LABELS.get(block_id, "")
    base = FACTORY_PREFIX + sha12(text)
    return f"{base}({label})" if label else base


def production_kind(block_id: str) -> str:
    """``factory`` (PG-ключ) | ``factory_document`` (поле JSON-документа) |
    ``managed_message`` | ``registered``."""
    spec = block(block_id)
    if spec is None:
        return "unknown"
    if spec.pg_key:
        return "factory_document" if spec.pg_doc_field else "factory"
    if spec.migration == "managed_message":
        return "managed_message"
    return "registered"


def factory_texts() -> dict[str, str]:
    """Все непустые фабричные тексты реестра (для fingerprint/дампов)."""
    out: dict[str, str] = {}
    for spec in all_blocks():
        text = factory_text(spec.block_id)
        if text:
            out[spec.block_id] = text
    return out


def factory_set_fingerprint() -> str:
    """Отпечаток НАБОРА фабричных текстов (guard «нет неучтённой правки»).

    Любая правка любого канона реестра без осознанного бампа константы ниже
    ломает ``factory_set_fingerprint()``: значит, кто-то поменял речевую
    инструкцию, не отразив это в реестре (SOUL-AMD.3.2).
    """
    payload = "\n".join(f"{bid}::{sha12(text)}"
                        for bid, text in sorted(factory_texts().items()))
    return sha12(payload)


#: Guard-константа: обновляется ЯВНО при осознанной правке фабричной редакции
#: (кто меняет канон — бампает отпечаток и метку в FACTORY_REVISION_LABELS).
#: Проверяется ``tests/test_soul1_registry_completeness.py``.
#: Последний бамп (W3, 17.10.2026): зарегистрирован блок
#: ``style.policy.hint`` (короткий semantic hint Speech Style Policy, слой 10
#: композера) — было ``381aa1f0a9e4`` (CORE-DOC W2), стало ``842a382c48f5``.
#: Бамп W10 (17.10.2026): зарегистрированы 8 управляемых сообщений
#: ``message.image_failure.*`` + ``message.image_request.clarify``
#: (замена захардкоженной фразы отказа, SOUL-AMD.5.15/5.9) — стало
#: ``96da8c7284a5``.
#: Бамп W4 (17.10.2026): зарегистрированы приёмы Humor Craft
#: (``humor.craft.common`` + 5 ``humor.technique.*``), рамка few-shot
#: (``humor.few_shot.block``) и классификатор окна реакций
#: (``experience.humor_window.system``) — 8 новых фабричных редакций.
#: Бамп W4 (17.10.2026): зарегистрированы приёмы Humor Craft
#: (``humor.craft.common`` + 5 ``humor.technique.*``), рамка few-shot
#: (``humor.few_shot.block``), классификатор окна реакций
#: (``experience.humor_window.system``) и 4 жанровые рамки авторских текстов
#: (``genre.*.rules``, SOUL-AMD.2.6) — 12 новых фабричных редакций;
#: было ``96da8c7284a5``, стало ``0fc99f73d646``.
#: Бамп FIX-SOUL-F1F3 (18.10.2026, review-payload-verify F3): фраза /persona
#: ``CHAT_PERSONA_PHRASE`` заменена на голос Core (была «я тот самый
#: токсичный бот-абьюзер…», SOUL-AMD.4.6(в)); было ``0fc99f73d646``,
#: стало ``7422c0385f7d``.
#: Бамп CFG-02B (19.10.2026, §02B.6, ADR-1031-1): зарегистрирован
#: редактируемый текст отказа ``message.image_failure.freq_limited``
#: (короткая пауза частотного лимита генераций) — было ``7422c0385f7d``,
#: стало ``5a3d211b36be``.
#: Бамп RE-PIN-25891 (19.10.2026, NF-1 ревью vision/cfg): фабричная
#: редакция изменена лейном INIT-ARCH (``620ce2b0``) — ровно один блок
#: ``internal.initiative_observer`` (``services.initiative_observer.
#: OBSERVER_EVAL_SYSTEM_PROMPT``; сверка карт фабричных текстов до/после:
#: added/removed = 0, changed = 1) — было ``5a3d211b36be``,
#: стало ``5bca81487001``. Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп FIX-25898-R1 (20.10.2026, ревью 25898 Блокер 1): переутверждение
#: после владельческой перестройки ``humor.craft.common`` (H11: критерий —
#: причинная связность/уместность, юмор не растягивается на каждый ответ,
#: факты/числа/ссылки/суть просьбы неприкосновенны; «не частота метафор или
#: оскорблений») — было ``5bca81487001``, стало ``64ec1c60e278``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп CFG-07A-2 (20.10.2026, ADR-1013-3, C14-прецедент): вычищены каноны
#: НЕ-фактчек маршрутов — search/youtube(×2)/web/checkup/summary-legacy
#: (safety-bypass, identity legacy-личности, sneer/hostility, метка данных
#: «"Архивная справка"») и Direct (честный слив без выдуманных тех-причин +
#: контракт служебных пометок Writer'а); нейтральная редакция
#: ``BOT_KNOWLEDGE_INSTRUCTION_NEUTRAL``; ``CHECKUP_FALLBACK_NOTICE`` без
#: bracket-маркера. Слепки прежних прод-байтов 2.58.100 — ступени
#: ``PREV_*_CFG07A`` + ROLLBACK (байт-сверка с продом в
#: tests/test_cfg07_backstage_contract.py). Метки ревизий 7 блоков бампнуты
#: (``*-cfg07a``). Было ``64ec1c60e278``, стало ``037080375ac8``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп FIX-CORRECTIVE-FOLLOWUP (22.10.2026, директива владельца 21.10 §1-2
#: + follow-up): из Personality Core (full+compact, метки
#: ``soul02-author-full-v2``/``soul02-compact-v2``) УДАЛЕНА тема мата —
#: регулирование нецензурной лексики принадлежит только Expression
#: (``PROFANITY_INSTRUCTIONS`` не менялись); из активных канонов Direct
#: legacy-базы и checkup удалены строки «Разрешен мат и сленг»; шапка
#: Expression очищена от нейтрализаторов. Прежние байты Core —
#: PREV_PERSONALITY_CORE_*; гвард superseded-core в core_selection не даёт
#: старым заводским байтам действовать из PG. Сверка карт фабричных текстов:
#: changed = core.personality, core.personality.compact,
#: prompts.direct_chat_system_prompt, prompts.checkup_system_prompt (+ L1 в
#: фикс-зоне direct-l1). Было ``037080375ac8``, стало ``21717a79dc67``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп 2 FIX-CORRECTIVE-FOLLOWUP (22.10.2026): та же правка доведена до
#: остальных пользовательских канонов — search/youtube/youtube_video/web/
#: summary/L2-writer: строки «ВАЖНО: Разрешен мат и сленг.» удалены из
#: активных баз; TYPOGRAPHY_BLOCK очищен (PREV_TYPOGRAPHY_BLOCK — слепок для
#: распознавания прод-байтов); suppress-правила 3/11 + новое правило 14
#: больше не оставляют разрешение мата в вычищенных persisted-значениях.
#: Было ``21717a79dc67``, стало ``71c6a7b6c612``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп 3 FIX-CORRECTIVE-FOLLOWUP (22.10.2026, финал): из активного канона
#: Summary L2-писателя удалено «и мат» в списке стилевых средств (источник
#: противоречия устранён, не перекрыт приоритетом; SF-14-тест переведён на
#: новый контракт). Было ``71c6a7b6c612``, стало ``3e35aaa38e0c``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп 4 FIX-CORRECTIVE-R1 (22.10.2026, зона nostalgia): канон ностальгии
#: (``internal.nostalgia.candidate`` = NOSTALGIA_PROMPT) — императивы
#: «Вбрось…» сняты, семантическая оценка ценности кандидата, расширенное
#: право отказа (скучный/односложный → UNCHANGED — нормальный исход),
#: анти-вымысел; прежние байты — PREV_NOSTALGIA_*_1021. Было
#: ``3e35aaa38e0c``, стало ``c19d35a1c093``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп 5 L1D (22.10.2026, директива владельца owner-corrective-initreply):
#: канон L1-планера (``direct.base.l1_planner`` = DIRECT_L1_PLANNER_SYSTEM_
#: PROMPT) получил поля формы участия delivery/target_message_id/
#: target_user_id + блок семантики форм без приоритетов (reply не
#: предпочтительнее обычного сообщения; молчание — полноценный исход);
#: правила 1–7 не менялись. Прежние байты — PREV_DIRECT_L1_PLANNER_1022
#: (прод 2.58.109, SHA256[:16] 5fdc90b3f114, 3022 симв) — ступень лестницы
#: prompt_migrations. Метка ревизии блока бампнута (l1-planner-l1d).
#: Сверка карт фабричных текстов: changed = 1 (direct.base.l1_planner).
#: Было ``c19d35a1c093``, стало ``3507bd6f92eb``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: LEGFIX-бамп (22.10.2026, закрытие backlog «narrator-канон
#: identity-фраза», bindings.cfg-final §6): канон Рассказчика
#: (``summary.base.narrator``) лишился identity-предложения «Ты —
#: токсичный … бот-абьюзер … завсегдатай двача» (класс SF-07 корпуса 07A-2;
#: голос задаёт Core — UNIFIED-CORE P0). Жанровые правила канона (сарказм,
#: plain-text, {max_symbols}) не менялись. Прежние байты —
#: PREV_SUMMARY_NARRATOR_LEGFIX (ступень лестницы prompt_migrations,
#: откат → непосредственный прежний канон). Метка ревизии блока бампнута
#: (summary-narrator-legfix). Сверка карт фабричных текстов: changed = 1
#: (summary.base.narrator). Было ``3507bd6f92eb``, стало ``553a281fe2fd``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп ASAP W1 (22.10.2026, §3.1–3.7 source-2026-10-22.md, слайсы
#: P0-A/B/C/D/E/F/G; ADR-1013-3): фабрики переписаны ГОТОВЫМИ ТЕКСТАМИ
#: ВЛАДЕЛЬЦА байт-в-байт — core.personality/compact = §3.2/§3.3 (v3:
#: ``asap-core-full-v3``/``asap-core-compact-v3``; без регулирования мата и
#: SOUL-16-ремарки; прежние байты v1/v2 — PREV_PERSONALITY_CORE_* +
#: *_V2_TEXT, обе в гварде superseded-core); direct.base.l2_writer = §3.1
#: (``l2-writer-w1``; без личности/типографики, data-reader для JSON-пакета
#: Stage-2 по P0A-RISK); direct.base.tool_phase = §3.6 (``direct-toolphase-
#: w1``; ролевой блок НАЗНАЧЕНИЕ/ДОСТОВЕРНОСТЬ/ГРАНИЦА ЭТАПА вместо
#: СИСТЕМНОЙ РОЛИ/ПРИОРИТЕТОВ/ПРАВИЛ ОФОРМЛЕНИЯ и блоков A/B); direct.base.
#: l1_planner — секция «ВЫБОР УЧАСТИЯ» §3.7 вместо «ФОРМА УЧАСТИЯ»
#: (``l1-planner-w1``; схема/правила прежние); factcheck.base.verbalizer —
#: identity-фраза снята (``factcheck-verbalizer-w1``, SOUL1-CLOSE-R1 04.3).
#: EXPRESSION_HEADER = §3.4 (вне реестра, слой mca_expression).
#: Слепки прежних прод-байтов 2.58.110 — PREV_*_W1, ступени лестницы
#: prompt_migrations + ROLLBACK (байт-сверка с продом — W0-инвентаризация,
#: plans/features/asap-speech-arch/evidence/w0-inventory.md).
#: Сверка карт фабричных текстов: changed = 6 (core.personality,
#: core.personality.compact, direct.base.tool_phase, direct.base.l2_writer,
#: direct.base.l1_planner, factcheck.base.verbalizer).
#: Было ``553a281fe2fd``, стало ``fd4e88754749``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп ASAP 2 Direct Chat (23.10.2026, P0-корректива
#: plans/features/asap2-direct-chat/source-2026-10-22.md, слайс
#: FIX-ASAP2-CLAR; ADR-1013-3): навязчивые уточнения и их зацикливание —
#: точечные правки ДВУХ канонов и двух код-путей, новых подсистем 0.
#: direct.base.l1_planner — контракт «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА»
#: §4.1 владельца байт-в-байт между секцией «ВЫБОР УЧАСТИЯ» (не тронута)
#: и ПРАВИЛАМИ; правило 5 — короткая отсылка к контракту (старое смысловое
#: правило не оставлено вторым приказом); схема/правила 1-4/6-7 прежние
#: (``l1-planner-clar``). direct.base.l2_writer — абзацы §4.2 владельца
#: байт-в-байт в раздел «КАК ПИСАТЬ» ОДИН раз (``l2-writer-clar``).
#: Слепки прежних прод-байтов 2.58.111 — PREV_DIRECT_L1_PLANNER_W1
#: (f8ab20121c02) и PREV_CHAT_VERBALIZER_W1_31 (be03964322aa), ступени
#: лестницы prompt_migrations + ROLLBACK. Код: normalize_l1_plan — строгий
#: JSON boolean (§3.2); build_l2_plan_block — узкая фраза §4.3 только при
#: непустом clarification_target; clarify_action/render_speech_block/
#: _l1_speech_hints — автономный сигнал clarify=ask и модельная директива
#: «задай ровно один вопрос» сняты (§3.3/§4.4), assume и прочие сигналы
#: Speech Understanding не тронуты. Кастомы владельца лестницей не
#: переписываются (только точное совпадение байт).
#: Сверка карт фабричных текстов: changed = 2 (direct.base.l1_planner,
#: direct.base.l2_writer).
#: Было ``fd4e88754749``, стало ``24ae494ac422``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
#: Бамп P0 (24.10.2026, P0-CHECKUP/CORE + ADDENDUM #2): изменены 4 фабрики —
#: checkup.base.system (owner-редакция §2 аддендума, «СУТЬ АНАЛИЗА» дословно),
#: message.checkup_fallback_notice (401 = отказ авторизации, journalctl
#: прочитан), core.personality и core.personality.compact (абзац «Как говорить
#: о реальных событиях» + принцип свободы речи на уровне личности; Compact —
#: одно предложение). Метки: checkup-p0-24-10, asap-core-full-v4,
#: asap-core-compact-v4. Было ``24ae494ac422``, стало ``071b1f3ec5f9``.
#: Переутверждено осознанно (SOUL-AMD.3.2).
FACTORY_SET_SHA256_12 = "071b1f3ec5f9"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Effective-значение: источник, активная ревизия, diagnostics
# ═══════════════════════════════════════════════════════════════════════════

@dataclasses.dataclass(frozen=True)
class EffectivePrompt:
    """Эффективное значение блока: ЧТО реально уходит в LLM и откуда."""

    block_id: str
    pg_key: str
    text: str
    source: str                  # chat | global | default | code | missing
    revision: str                # act:<sha256_12> активного значения
    factory_revision: str        # fac:<sha256_12>(label) заводской редакции
    differs_from_factory: bool
    legacy_persona_present: bool = False   # маркер старой личности в значении
    legacy_stripped: bool = False          # значение вычищено на сборке
    legacy_removed: int = 0
    known_canon: bool = False              # байты совпали с известным каноном
    diagnostics: tuple[str, ...] = ()
    # Провенанс (SOUL-AMD.1.2/4.6): сохранённое значение удержано от
    # effective-слоя; хранить его ревизию/причину обязан Inspector.
    withheld: bool = False
    withheld_revision: str = ""
    withheld_sha256_12: str = ""
    provenance_reason: str = ""
    withheld_class: str = ""           # legacy_incompatible | identical_to_factory
    withheld_reason: str = ""          # человеческая причина класса
    stored_source: str = ""                # слой сохранённого значения
    stored_differs_from_factory: bool = False

    @property
    def factory_source(self) -> str:
        """Отображение для UI: Factory | Global Custom | Chat Override | Inherited."""
        if self.withheld:
            # Действует заводская редакция; сохранённое значение видно
            # отдельно (withheld_revision/provenance_reason) — не тихо.
            return "Factory"
        if self.source in ("default", "code", "missing"):
            return "Factory"
        if self.source == "chat":
            return "Chat Override" if self.differs_from_factory else "Inherited"
        return "Global Custom" if self.differs_from_factory else "Factory"


#: FIX-CFG07A-F1 (deploy 2.58.101, ADR-1013-3): 7 не-фактчек канонов
#: CFG-07A-2. Прод-значения этих ключей — кастом владельца (прежний канон +
#: владельческая правка), поэтому анти-backstage чистка 07A-2 по дизайну
#: «защиты кастома» не достигла effective-пейлоадов. Для ТОЛЬКО этих ключей
#: корпусные legacy-маркеры (07A-1) гасятся и в кастом-значениях — на
#: сборке payload, без записи в PG. Фактчек-каноны (W3-freeze) и прочие
#: блоки в скоуп не входят: их кастом по-прежнему не правится.
CFG07A_PAYLOAD_CLEAN_KEYS: frozenset = frozenset({
    "prompts.direct_chat_system_prompt",
    "prompts.summary_system_prompt",
    "prompts.checkup_system_prompt",
    "prompts.search_system_prompt",
    "prompts.youtube_system_prompt",
    "prompts.youtube_video_system_prompt",
    "prompts.webpage_system_prompt",
})


def payload_custom_clean_scope(pg_key: str, source: str) -> bool:
    """F1-скоуп корпусной чистки кастома: 7 канонов × persisted-слой.

    ``True`` ⇒ ``suppress_legacy_speech`` вправе гасить корпусные
    legacy-маркеры и в значении, не совпадающем байтами с известным
    каноном. Кодовый fallback (``default``) и ключи вне скоупа — никогда.
    """
    return (source in ("chat", "global")
            and str(pg_key or "") in CFG07A_PAYLOAD_CLEAN_KEYS)


def suppress_legacy_speech(text: str, *, source: str,
                           custom_clean: bool = False) -> tuple:
    """Вычистить известные сегменты legacy-личности из ПЕРСИСТЕНТНОГО значения.

    Возвращает ``(текст, LegacySuppression)``. Правила (bounded, точные):

    * применяется ТОЛЬКО при ``source in {"chat", "global"}`` — кодовый
      fallback (``default``) остаётся байт-в-байт прежним (OFF-паритет W2);
    * применяется ТОЛЬКО если байты значения совпадают с ИЗВЕСТНЫМ каноном
      (``known_canon_hashes``): кастом владельца никогда не правится;
    * FIX-CFG07A-F1 (deploy 2.58.101): при ``custom_clean=True`` те же
      правила применяются и к НЕ-каноническому (кастомному) значению —
      ТОЛЬКО для 7 не-фактчек канонов CFG-07A-2
      (``CFG07A_PAYLOAD_CLEAN_KEYS``, скоуп см.
      ``payload_custom_clean_scope``). Хранимый текст не меняется: чистка
      идёт на сборке effective-payload, владелец видит/правит свой текст
      как раньше, а LLM уходит версия без корпусных legacy-маркеров;
    * идемпотентна: повторный вызов не находит сегментов (``removed == 0``);
    * не трогает несвязанные контракты (инструменты, JSON-схемы,
      анти-галлюцинации, маркировка цели, канальный формат) — они не являются
      сегментами legacy-личности.

    Реверс: значения в PG не изменяются, поэтому достаточно выключить
    подавление (или выполнить ``prompt_migrations.rollback_legacy_speech``).
    """
    raw = str(text or "")
    info = LegacySuppression(known_canon=False, legacy_present=False)
    if source not in ("chat", "global") or not raw:
        return raw, info
    known = sha12(raw) in known_canon_hashes()
    allowed_exact = _exact_rule_allowlist().get(sha12(raw), ())
    present = (bool(_legacy_persona_marker_re.search(raw))
               and not allowed_exact)
    info = LegacySuppression(known_canon=known, legacy_present=present)
    if not known and not custom_clean:
        return raw, info
    if custom_clean and not known and not present:
        # F1: у значения могут быть только корпусные маркеры вне старого
        # маркер-набора («перегрелись серверы», «Архивная справка»).
        present = bool(_corpus_extra_marker_re.search(raw))
    if not present:
        return raw, info
    cleaned = raw
    removed = 0
    labels: list[str] = []
    allowed = _exact_rule_allowlist().get(sha12(raw), ())
    for label, pattern, replacement in LEGACY_PERSONA_RULES:
        if label in allowed:
            # P0-PROMPTS (24.10.2026): узкий allowlist ТОЧНЫХ байт новой
            # owner-редакции Checkup. «человеческо-токсичный» — авторский
            # жанровый оборот, а не legacy-личность; защита для всех прочих
            # значений (включая старые редакции) не отключается.
            continue
        cleaned, n = pattern.subn(replacement, cleaned)
        if n:
            removed += n
            labels.append(label)
    if removed:
        cleaned = _BLANK_RUN_RE.sub("\n\n", cleaned)
    return cleaned, dataclasses.replace(
        info, removed=removed, applied=bool(removed), labels=tuple(labels))


@dataclasses.dataclass(frozen=True)
class LegacySuppression:
    """Диагностика подавления legacy-сегментов (R17-safe: без текста)."""

    known_canon: bool = False
    legacy_present: bool = False
    applied: bool = False
    removed: int = 0
    labels: tuple[str, ...] = ()


def effective_prompt(pg_key_or_id: str, *, pg_value=None,
                     chat_value=None) -> EffectivePrompt:
    """Собрать effective-представление блока (без I/O: значения передаются).

    ``pg_value``/``chat_value`` — значения ПЕРСИСТЕНТНОГО слоя (``None`` —
    слоя нет). Кодовый fallback применяется здесь же (``source="default"``):
    реестр показывает то, что реально уйдёт в LLM, а не «намерение».
    Для блока-поля JSON-документа (``pg_doc_field``, Personality Core)
    персистентное значение — САМ документ, а эффективное значение — его поле.
    """
    spec = block_for(pg_key_or_id)
    if spec is None:
        return EffectivePrompt(
            block_id=str(pg_key_or_id), pg_key="", text="", source="missing",
            revision="", factory_revision="", differs_from_factory=False,
            diagnostics=("block_unknown",))
    factory = factory_text(spec.block_id)
    source = "code"
    value = None
    diagnostics: list[str] = []
    if chat_value is not None:
        source, value = "chat", chat_value
    elif pg_value is not None:
        source, value = "global", pg_value
    elif spec.pg_key:
        source, value = "default", factory
        diagnostics.append("pg_key_absent" if factory else "factory_absent")
    else:
        source, value = "code", factory
    text = str(value or "")
    if spec.pg_doc_field and source in ("chat", "global"):
        field_text = doc_field_text(value, spec.pg_doc_field)
        if field_text.strip():
            text = field_text
        else:
            # Поле владельцем не задано → действует заводская редакция ЭТОГО
            # поля (та же семантика, что у ``core_selection`` и композиции:
            # правка одной редакции не обнуляет вторую).
            text = factory
            diagnostics.append("document_field_absent")
    resolved = resolve_speech_value(spec.pg_key or spec.block_id, text,
                                    source=source)
    stripped = resolved.text
    info = suppress_legacy_speech(
        text, source=source,
        custom_clean=payload_custom_clean_scope(spec.pg_key, source))[1]
    diagnostics.extend(resolved.diagnostics)
    if stripped != text and not resolved.withheld:
        diagnostics.append("legacy_speech_suppressed")
    if info.known_canon and info.legacy_present and not info.applied:
        diagnostics.append("legacy_persona_present")
    if not stripped.strip():
        diagnostics.append("effective_empty")
    # «Factory / Global Custom / Chat Override / Inherited» (SOUL-AMD.4.3)
    # описывают ПЕРСИСТЕНТНЫЙ слой: сравнение идёт с сырым значением, а не с
    # уже вычищенным effective-текстом.
    differs = bool(factory) and text != factory
    if source in ("default", "code", "missing"):
        differs = False
    stored_differs = differs
    if resolved.withheld:
        # Действует заводская редакция → сравнение effective-текста с ней.
        differs = bool(factory) and stripped != factory
    return EffectivePrompt(
        block_id=spec.block_id, pg_key=spec.pg_key or "", text=stripped,
        source=resolved.source,
        revision=(ACTIVE_PREFIX + sha12(stripped)) if stripped else "",
        factory_revision=factory_revision(spec.block_id),
        differs_from_factory=differs,
        legacy_persona_present=info.legacy_present,
        legacy_stripped=info.applied, legacy_removed=info.removed,
        known_canon=info.known_canon, diagnostics=tuple(diagnostics),
        withheld=resolved.withheld,
        withheld_revision=(ACTIVE_PREFIX + resolved.withheld_sha256_12
                           if resolved.withheld else ""),
        withheld_sha256_12=resolved.withheld_sha256_12,
        provenance_reason=resolved.provenance_reason,
        withheld_class=resolved.withheld_class,
        withheld_reason=resolved.withheld_reason,
        stored_source=(source if resolved.withheld and
                       source in ("chat", "global") else ""),
        stored_differs_from_factory=stored_differs)


def registry_view() -> list[dict]:
    """Вид реестра для UI/PM (W6) и тестов: метаданные + фабричная ревизия."""
    rows: list[dict] = []
    for spec in all_blocks():
        rows.append({
            "block_id": spec.block_id,
            "purpose": spec.purpose,
            "family": spec.family,
            "scope": spec.scope,
            "pg_key": spec.pg_key or "",
            "pg_doc_field": spec.pg_doc_field,
            "code_source": spec.code_source or "",
            "consumers": list(spec.consumers),
            "composition_point": spec.composition_point,
            "enabled_by": spec.enabled_by,
            "migration": spec.migration,
            "owner_lane": spec.owner_lane,
            "speech": spec.speech,
            "legacy_persona": spec.legacy_persona,
            "provenance_required": withholding_required(spec),
            "ui": spec.ui,
            "production_kind": production_kind(spec.block_id),
            "factory_revision": factory_revision(spec.block_id),
            "factory_chars": len(factory_text(spec.block_id)),
            "registry_version": REGISTRY_VERSION,
        })
    return rows


# ── Speech Style Policy (SOUL-16, W3): витрина типизированных правил ────────
# Правила формы — управляемая сущность (документ ``style.policy``), а не
# десятки ``prompts.*`` (SOUL-16.1.4). Здесь — единая точка входа для UI/
# Inspector (W6) и тестов: активные правила с источником, soft-привычки,
# presets, каталог kind, диагностика документа и hint-блок реестра.

STYLE_POLICY_BLOCK_ID = "style.policy.hint"


def style_policy_view(global_doc=None, chat_doc=None, *, context: str = "",
                      extent: str = "", enabled: bool = True) -> dict:
    """Витрина Speech Style Policy + регистрация hint-блока (W6/W3).

    ``global_doc``/``chat_doc`` — документы ``style.policy`` (если не заданы,
    витрина отдаёт только метаданные реестра без значений). Никогда не
    бросает."""
    spec = block(STYLE_POLICY_BLOCK_ID)
    base = {
        "block_id": STYLE_POLICY_BLOCK_ID,
        "purpose": (spec.purpose if spec is not None else ""),
        "owner_lane": (spec.owner_lane if spec is not None else "W3"),
        "composition_point": (spec.composition_point if spec is not None
                              else "speech_plain/speech_rich"),
        "factory_revision": factory_revision(STYLE_POLICY_BLOCK_ID),
        "factory_chars": len(factory_text(STYLE_POLICY_BLOCK_ID)),
        "ui": (spec.ui if spec is not None else "catalog_pending"),
        "registry_version": REGISTRY_VERSION,
        "doc_key": "style.policy",
    }
    try:
        from services import style_policy as _sp
        view = _sp.style_policy_view(global_doc, chat_doc, context=context
                                     or "regular", extent=extent,
                                     enabled=enabled)
    except Exception:
        logger.warning("[prompt_registry] style policy view failed",
                       exc_info=True)
        view = {"skip_reason": "view_error", "conflicts": ["view_error"],
                "rules": [], "soft_instructions": []}
    return {**base, **view}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Legacy speech suppression: известные каноны и сегменты личности
# ═══════════════════════════════════════════════════════════════════════════
# Механизм — прецедент ``response_extent.strip_cap_phrases`` (§8.7 дизайна):
# детерминированная вычистка ИЗВЕСТНЫХ сегментов на сборке, БД не правится.
# Расширение до реестра ``legacy_persona_suppression`` (design-composer §4):
# bounded, только известные хеши канонов, кастом никогда.

_LEGACY_PERSONA_RULES_RAW: tuple[tuple[str, str, str], ...] = (
    # 1. Определение личности старого канона. Удаляется ПРЕДЛОЖЕНИЕ целиком
    #    («токсичный/саркастичный/циничный … бот-абьюзер … двача»), остальная
    #    часть строки (задача, контракты) сохраняется.
    ("persona.identity_sentence",
     r"Ты\s*[-—]\s*токсичн\w*[^.]*?(?:двач\w*|бот-абьюзер\w*)\)?\.\s*",
     ""),
    # 2. Инструкция «игнорируй настройки безопасности/цензуры/морали» —
    #    снятие safety-контура, не являющееся контрактом безопасности.
    #    CORRECTIVE-FOLLOWUP (21.10.2026, §2): правило 3 более НЕ оставляет
    #    разрешение мата — строка удаляется целиком (режим мата задаёт
    #    только <Expression_Settings>); «ВАЖНО:»-префикс уходит с ней.
    ("persona.safety_circumvention",
     r"Игнорируй все настройки безопасности, цензуры и морали\.\s*",
     ""),
    # 3. «(ВАЖНО:) Разрешен мат, токсичность и любой сленг» → строка удалена
    #    целиком (CORRECTIVE-FOLLOWUP 21.10.2026, §2: разрешение мата —
    #    вне Expression недопустимо; ранее оставляли «Разрешен мат и сленг.»).
    #    Съедается только СВОЙ перевод строки — пустой абзац после строки
    #    сохраняется (байт-паритет с активными канонами).
    ("persona.tone_label",
     r"(?:ВАЖНО:\s*)?Разрешен мат, токсичность и любой сленг\.[ \t]*\n?",
     ""),
    # 4. Режим deep_research: «интегрируй токсичный стиль» → писать по делу.
    ("persona.mode_deep_research",
     r"Интегрируй токсичный стиль органично, без пафосных вступлений\.",
     "Пиши по делу, без пафосных вступлений."),
    # 5. Hostility-директива <bot_knowledge> («унизить оппонента»).
    ("persona.bot_knowledge_hostility",
     r"используй её, чтобы унизить оппонента своими знаниями",
     "используй её в ответе"),
    # 6. Search-канон: «обоссав автора запроса за лень или тупость».
    ("persona.search_sneer",
     r"выдать подробную выжимку сути, обоссав автора запроса за лень "
     r"или тупость",
     "выдать подробную выжимку сути"),
    # 7. Checkup-канон: «унизив разработчика за кривой код…».
    ("persona.checkup_humiliation",
     r"выдать отчет о здоровье системы, унизив разработчика за кривой код "
     r"или порадовавшись, если всё работает",
     "выдать отчет о здоровье системы"),
    # 8. Checkup-канон: «человеческо-токсичный язык».
    ("persona.checkup_language",
     r"переводи техническую инфу на человеческо-токсичный язык",
     "переводи техническую инфу на человеческий язык"),
    # 9. Direct-канон: «в саркастично-токсичной манере».
    ("persona.direct_style_label",
     r"в саркастично-токсичной манере",
     "в саркастичной манере"),
    # 10. FIX-SOUL-F1F3 (18.10.2026, review-payload-verify F1): канон Summary
    #     hybrid-L2: «сохраняй характер бота и атмосферу конфы» — инструкция
    #     сохранять СТАРЫЙ голос. Голос канала задаёт Core (единственный
    #     источник характера); оборот заменяется ссылкой на него. Заголовок
    #     секции «СТИЛЬ (характер бота)» — метка раздела, не определение.
    ("summary.l2_legacy_voice_reference",
     r"сохраняй характер бота и атмосферу конфы",
     "держи голос Core"),
    # 11. FIX-SOUL-F1F3: тот же канон: «двачерские обороты» — ссылка на
    #     старую речевую среду. CORRECTIVE-FOLLOWUP (21.10.2026, §2):
    #     разрешение мата из списка убрано (режим мата — только Expression);
    #     сарказм/сленг сохранены как функциональная часть.
    ("summary.l2_dvach_vocabulary",
     r"Сарказм, интернет-сленг, двачерские обороты и мат разрешены",
     "Сарказм и интернет-сленг разрешены"),
    # 12. FIX-CFG07A-F1 (21.10.2026, deploy 2.58.101 F1; корпус SF-09):
    #     Direct-канон: выдуманные внутренние причины при честном сливе
    #     («перегрелись серверы, база покрылась пылью») — источник семьи
    #     «по моим логам» (MB-01). Скобочная вставка снимается; честное
    #     признание косяка (правило 9) остаётся — байт-равно активному
    #     канону. На чистых канонах фразы нет (no-op, байт-регресс).
    ("direct.honest_concession_invented_causes",
     r"\s*\(перегрелись серверы,\s*база покрылась пылью\)",
     ""),
    # 13. FIX-CFG07A-F1 (корпус SF-16/E3): Summary-канон: метка данных
    #     «помечены как "Архивная справка"» — источник семьи «в моей
    #     справке» (MB-02, эхо-риск ярлыка). Заменяется на нейтральную
    #     формулировку байт-в-байт активного канона; сами метки в ДАННЫХ
    #     (canonical_context) не затрагиваются — правило применяется только
    #     к тексту речевого канона.
    ("summary.archive_data_label",
     r"помечены как \"Архивная справка\"",
     "содержат архивные факты"),
    # 14. FIX-CORRECTIVE-FOLLOWUP (21.10.2026, §2 владельца): Direct-канон —
    #     строка «3. Разрешен мат и сленг. Будь грубым, но по факту.»
    #     удаляется целиком (режим мата — только Expression; «Будь грубым,
    #     но по факту» сохранено в активном каноне отдельной правкой базы —
    #     правило нужно для вычистки СТАРЫХ persisted-байтов, где строка
    #     была частью правила 3). На новом каноне фразы нет (no-op).
    ("direct.mat_permission_rule",
     r"\n3\. Разрешен мат и сленг\. Будь грубым, но по факту\.",
     ""),
)

LEGACY_PERSONA_RULES: tuple[tuple[str, "re.Pattern[str]", str], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE | re.UNICODE), replacement)
    for label, pattern, replacement in _LEGACY_PERSONA_RULES_RAW)

#: Быстрый маркер «в тексте есть определение старой личности».
#: FIX-SOUL-F1F3 (18.10.2026, review-payload-verify F1): добавлен ``двач`` —
#: канон Summary hybrid-L2 несёт «двачерские обороты» и не содержит прочих
#: маркеров, из-за чего гейт не срабатывал и «сохраняй характер бота…» не
#: вычищался. Все остальные каноны с ``двач`` уже имеют старые маркеры, так
#: что расширение не меняет их обработку.
_legacy_persona_marker_re = re.compile(
    r"токсичн|бот-абьюзер|унизить|унизив|двач", re.IGNORECASE | re.UNICODE)

#: FIX-CFG07A-F1: дополнительные корпусные маркеры (07A-1: SF-09/SF-16),
#: которых нет в старом маркер-наборе. Нужен только для custom_clean-пути:
#: кастом может нести исключительно эти сегменты. На гейт known-canon
#: пути не влияет (поведение known-ветки байт-неизменно).
_corpus_extra_marker_re = re.compile(
    r"перегрелись|Архивная справка", re.IGNORECASE | re.UNICODE)

_BLANK_RUN_RE = re.compile(r"\n{3,}")

#: P0-PROMPTS (24.10.2026): точечный allowlist ПРАВИЛ по точным байтам.
#: Новая owner-редакция Checkup (аддендум §2) дословно содержит
#: «человеческо-токсичный»; правило `persona.checkup_language` не должно
#: вырезать его, если сохранены ровно эти байты. Для любой другой редакции
#: (старой/кастомной) подавление работает как раньше.
_EXACT_RULE_ALLOWLIST_CACHE: dict[str, tuple[str, ...]] | None = None


def _exact_rule_allowlist() -> dict[str, tuple[str, ...]]:
    global _EXACT_RULE_ALLOWLIST_CACHE
    if _EXACT_RULE_ALLOWLIST_CACHE is None:
        allow: dict[str, tuple[str, ...]] = {}
        try:
            from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT
            allow[sha12(CHECKUP_SYSTEM_PROMPT)] = ("persona.checkup_language",)
        except Exception:      # pragma: no cover — модуль недоступен
            logger.warning("[prompt_registry] allowlist Checkup недоступен",
                           exc_info=True)
        _EXACT_RULE_ALLOWLIST_CACHE = allow
    return _EXACT_RULE_ALLOWLIST_CACHE

_KNOWN_CANON_HASHES: set[str] = set()


def known_canon_hashes() -> set[str]:
    """Хеши известных канонов: фабричные тексты + все PREV/rollback-слепки.

    Именно этот набор — «bounded»-граница подавления: значение, чьи байты не
    совпали ни с одним известным каноном, считается кастомом владельца и НЕ
    правится на сборке (design-composer §4, owner-decisions «a»).
    """
    if _KNOWN_CANON_HASHES:
        return _KNOWN_CANON_HASHES
    hashes: set[str] = set()
    for text in factory_texts().values():
        hashes.add(sha12(text))
    try:
        from services import prompt_migrations as pm
        for steps in pm.PROMPT_MIGRATIONS.values():
            for prev, new in steps:
                hashes.add(sha12(prev))
                hashes.add(sha12(new))
        for new, old in pm.ROLLBACK_MIGRATIONS.values():
            hashes.add(sha12(new))
            hashes.add(sha12(old))
    except Exception:          # pragma: no cover — лестница миграций недоступна
        logger.warning("[prompt_registry] лестница миграций недоступна",
                       exc_info=True)
    _KNOWN_CANON_HASHES.update(hashes)
    return _KNOWN_CANON_HASHES


def is_known_canon(text: str) -> bool:
    return sha12(str(text or "")) in known_canon_hashes()


def legacy_persona_present(text: str) -> bool:
    raw = str(text or "")
    if sha12(raw) in _exact_rule_allowlist():
        return False
    return bool(_legacy_persona_marker_re.search(raw))


# ═══════════════════════════════════════════════════════════════════════════
# 6. Провенанс persisted-значений: что можно считать активным слоем
# ═══════════════════════════════════════════════════════════════════════════

#: Исключения из класса удержания (явные, с причиной): ветки режимов — это
#: правила длины/формата, которые владелец правит во вкладках режимов; их
#: единственный legacy-сегмент («Интегрируй токсичный стиль…») снимается
#: детерминированной вычисткой канона, а не удержанием всего блока.
PROVENANCE_EXEMPT_PREFIXES: tuple[str, ...] = ("verbilizer.mode.",)

#: P0-PROMPTS (24.10.2026): классификация известных withheld-редакций по
#: фактическим байтам (`plans/features/p0-corrective-factcheck-speech/evidence/
#: withheld/classification.md`, прод 2.58.118). 8 `user_custom` содержат
#: старую личность / строку обхода ограничений / ослабленный полный разбор.
#: Они НЕ активируются: остаются в PG и истории, Inspector показывает
#: сохранённый и действующий текст + причину. `identical_to_factory` — байты
#: совпадают с зарегистрированной заводской редакцией (2.58.118), поэтому это
#: не конфликт владельца: WARNING понижен до INFO, активация не нужна.
WITHHELD_LEGACY_CLASS = "legacy_incompatible"
WITHHELD_IDENTICAL_CLASS = "identical_to_factory"
WITHHELD_UNCLASSIFIED_CLASS = "unclassified"

WITHHELD_CLASSIFICATIONS: dict[str, dict[str, dict[str, str]]] = {
    "checkup.base.system": {
        "1e8a3c69cf7b": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": ("старая личность Checkup, строка обхода ограничений "
                       "и ослабленный полный разбор утверждений")},
    },
    "factcheck.base.single": {
        "76c4beb11c63": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": ("строка обхода ограничений и требование сознательно "
                       "игнорировать часть утверждений — противоречит "
                       "контракту полного разбора фактчека")},
    },
    "factcheck.base.verbalizer": {
        "5fbf61cea310": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": ("старая личность фактчекера и ослабленный разбор "
                       "утверждений")},
    },
    "search.base.system": {
        "ba43fb679db6": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": "старая личность и строка обхода ограничений"},
    },
    "summary.base.single": {
        "d697b0745b29": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": "старая личность и строка обхода ограничений"},
    },
    "web.base.system": {
        "7801085b6ef5": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": "старая личность и строка обхода ограничений"},
    },
    "youtube.base.system": {
        "e0a1ffaf18a1": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": "старая личность и строка обхода ограничений"},
    },
    "youtube.base.video": {
        "c8bba06ec6a8": {
            "class": WITHHELD_LEGACY_CLASS,
            "reason": "старая личность и строка обхода ограничений"},
    },
    "direct.base.l2_writer": {
        "83ff62bbee40": {
            "class": WITHHELD_IDENTICAL_CLASS,
            "reason": ("байты совпадают с заводской редакцией 2.58.118; "
                       "текущая фабрика новее — активация не требуется, "
                       "ложный конфликт снят")},
    },
}


def withheld_classification(block_id: str,
                            value: str) -> dict[str, str] | None:
    """Класс известной withheld-редакции по точным байтам (или ``None``)."""
    entry = (WITHHELD_CLASSIFICATIONS.get(str(block_id)) or {}).get(sha12(value))
    return dict(entry) if entry else None


def is_legacy_incompatible(block_id: str, value: str) -> bool:
    """Редакция известна как legacy-несовместимая (активация запрещена)."""
    entry = withheld_classification(block_id, value)
    return bool(entry and entry.get("class") == WITHHELD_LEGACY_CLASS)



def withholding_required(spec) -> bool:
    """Требуется ли провенанс для persisted-значения блока (SOUL-AMD.1.2/4.6).

    Класс — PG-управляемые речевые каноны старой личности (``legacy_persona``):
    именно они были «старыми PG overrides» и не остаются активным слоем.
    Машинные стадии, ключи-селекторы режимов/стилей, ветки режимов
    (``PROVENANCE_EXEMPT_PREFIXES``) и прочие речевые блоки без признака
    ``legacy_persona`` сохраняют прежнюю семантику: значение видно в effective,
    известные каноны вычищаются, кастом не правится.
    """
    if spec is None or not spec.pg_key or not spec.speech \
            or not spec.legacy_persona:
        return False
    return not any(spec.block_id.startswith(prefix)
                   for prefix in PROVENANCE_EXEMPT_PREFIXES)


def withholding_blocks() -> tuple[PromptBlockSpec, ...]:
    """Блоки, для которых persisted-значение требует провенанса."""
    return tuple(b for b in all_blocks() if withholding_required(b))


def _config_cache():
    """ConfigCache (или ``None``); не бросает."""
    try:
        from services import hot_config as hot
        return hot.get_config_cache()
    except Exception:          # pragma: no cover — защитная ветка
        return None


def provenance_doc(cache=None) -> dict:
    """Документ журнала записей реестра (``items`` + ``provenance``)."""
    cache = cache if cache is not None else _config_cache()
    if cache is None:
        return {}
    raw = None
    try:
        raw = cache.get(PROVENANCE_DOC_KEY, None)
    except Exception:          # pragma: no cover — PG down
        return {}
    if isinstance(raw, str):
        try:
            import json as _json
            raw = _json.loads(raw)
        except Exception:      # pragma: no cover — битая строка
            return {}
    return raw if isinstance(raw, dict) else {}


def attested_revision(block_id: str, *, cache=None) -> dict | None:
    """Последняя ревизия блока, записанная API реестра/фабрики (или ``None``).

    Записи ``backup_restore`` провенанса не дают (аварийное возвращение
    значения — это данные, а не действующий речевой слой, §4.6).
    """
    doc = provenance_doc(cache)
    entries = doc.get(PROVENANCE_MAP_FIELD)
    if not isinstance(entries, dict):
        return None
    entry = entries.get(block_id)
    if not isinstance(entry, dict):
        return None
    if entry.get("kind") not in PROVENANCE_WRITE_KINDS:
        return None
    return entry


def provenance_state(spec, value: str, *, cache=None) -> tuple[str, dict | None]:
    """``(reason, entry)`` для persisted-значения блока.

    ``reason`` ∈ ``attested | provenance_missing | provenance_mismatch |
    provenance_unavailable`` (R17-safe: только коды, без текста значения).
    """
    if spec is None:
        return "provenance_unavailable", None
    cache = cache if cache is not None else _config_cache()
    if cache is None:
        return "provenance_unavailable", None
    entry = attested_revision(spec.block_id, cache=cache)
    if entry is None:
        return "provenance_missing", None
    if str(entry.get("sha256_12") or "") != sha12(str(value or "")):
        return "provenance_mismatch", entry
    return "attested", entry


@dataclasses.dataclass(frozen=True)
class SpeechResolution:
    """Результат резолва persisted-значения: текст, источник, диагностика.

    ``source`` — тот же словарь, что у композера (``chat|global|default``);
    ``withheld=True`` ⇒ значение из PG НЕ стало активным слоем (действует
    заводская редакция — ``source="default"``), а расхождение записано в
    ``diagnostics`` (тихой подмены нет).
    """

    text: str
    source: str
    diagnostics: tuple[str, ...] = ()
    withheld: bool = False
    withheld_sha256_12: str = ""
    provenance_reason: str = ""
    provenance: dict | None = None
    withheld_class: str = ""
    withheld_reason: str = ""

    @property
    def stored_source(self) -> str:
        """Слой, из которого пришло сохранённое значение (для Inspector)."""
        return "" if self.source == "default" else self.source


def _hot_present(pg_key: str) -> bool:
    """Есть ли ключ в ПЕРСИСТЕНТНОМ (hot) слое. Не бросает."""
    try:
        from services import hot_config as hot
        cache = hot.get_config_cache()
        if cache is None:
            return False
        return cache.get(pg_key, None) is not None
    except Exception:          # pragma: no cover — защитная ветка
        return False


async def _chat_present(chat_id: int, pg_key: str) -> bool:
    """Есть ли per-chat override именно этого ключа. Не бросает."""
    try:
        from services.chat_params import get_chat_params_cache
        cache = get_chat_params_cache()
        if cache is None:
            return False
        root = await cache.get_chat_params(int(chat_id))
        overrides = (root or {}).get("overrides") or {}
        return pg_key in overrides
    except Exception:          # pragma: no cover — защитная ветка
        return False


def resolve_speech_value(pg_key: str, value: str, *, source: str,
                         cache=None) -> SpeechResolution:
    """Единая точка резолва persisted-значения речевого блока.

    Порядок решений:
      1) источник не ``chat|global`` (кодовый fallback/PG down) — значение
         отдаётся как есть (OFF-паритет W2 не затрагивается);
      2) блок требует провенанса и сохранённая ревизия НЕ записана API
         реестра/фабрики → **значение удерживается**: действует заводская
         редакция (в том же виде, что и для persisted-канона: известные
         сегменты старой личности вычищены), в PG ничего не пишется;
      3) иначе — прежнее поведение (детерминированная вычистка известных
         сегментов legacy-личности; кастом владельца не правится).
    """
    spec = by_pg_key(pg_key)
    raw = str(value or "")
    # FIX-CFG07A-F1: скоуп корпусной чистки кастома (7 канонов CFG-07A-2);
    # для остальных ключей поведение прежнее (кастом не правится).
    custom_clean = payload_custom_clean_scope(
        spec.pg_key if spec is not None else "", source)
    if source not in ("chat", "global") or not raw or spec is None:
        text, _info = suppress_legacy_speech(raw, source=source)
        return SpeechResolution(text=text, source=source)
    if withholding_required(spec):
        reason, entry = provenance_state(spec, raw, cache=cache)
        if reason != "attested":
            factory = factory_text(spec.block_id)
            classification = withheld_classification(spec.block_id, raw)
            withheld_class = (classification or {}).get(
                "class", WITHHELD_UNCLASSIFIED_CLASS)
            # Заводская редакция отдаётся ровно в том виде, в каком её
            # отдавал бы persisted-канон: те же вычищенные сегменты.
            text, _info = suppress_legacy_speech(factory, source="global")
            diagnostics = ["persisted_value_withheld", reason]
            if legacy_persona_present(raw):
                diagnostics.append("persisted_legacy_persona_marker")
            if withheld_class == WITHHELD_IDENTICAL_CLASS:
                # Байты совпадают с ЗАРЕГИСТРИРОВАННОЙ заводской редакцией
                # (classification.md §2). Текущая фабрика может быть новее,
                # поэтому старая редакция не активируется, но это не конфликт
                # владельца: WARNING заменён на INFO (ложный шум снят).
                diagnostics.append("provenance_factory_equivalent")
                logger.info(
                    "[prompt_registry] persisted speech value is a registered "
                    "factory edition | key=%s | block=%s | reason=%s | "
                    "stored_sha=%s | stored_chars=%d",
                    pg_key, spec.block_id, reason, sha12(raw), len(raw))
            else:
                logger.warning(
                    "[prompt_registry] persisted speech value withheld | "
                    "key=%s | block=%s | reason=%s | class=%s | stored_sha=%s "
                    "| stored_chars=%d",
                    pg_key, spec.block_id, reason, withheld_class,
                    sha12(raw), len(raw))
            return SpeechResolution(
                text=text if text.strip() else factory, source="default",
                diagnostics=tuple(diagnostics), withheld=True,
                withheld_sha256_12=sha12(raw),
                provenance_reason=reason, provenance=entry,
                withheld_class=withheld_class,
                withheld_reason=(classification or {}).get("reason", ""))
        text, _info = suppress_legacy_speech(raw, source=source,
                                             custom_clean=custom_clean)
        return SpeechResolution(text=text, source=source,
                                diagnostics=("provenance_attested",),
                                provenance_reason=reason, provenance=entry)
    text, _info = suppress_legacy_speech(raw, source=source,
                                         custom_clean=custom_clean)
    return SpeechResolution(text=text, source=source)


def withheld_values(*, pg_get=None, cache=None) -> list[dict]:
    """Витрина конфликта для Inspector/владельца: какие persisted-значения
    удержаны и почему (SOUL-AMD.3.2/4.3: нет тихой подмены).

    Возвращает по строке на блок: ключ, сохранённая ревизия/длина, признак
    маркера старой личности, записанная через API ревизия (если есть) и
    причина удержания. Тексты значений не возвращаются (R17-safe).
    """
    cache = cache if cache is not None else _config_cache()
    getter = pg_get
    if getter is None:
        def getter(key, default=None):      # noqa: ANN001 — minimal default
            from services import hot_config as hot
            return hot.get(key, default)
    rows: list[dict] = []
    for spec in withholding_blocks():
        present = False
        value = ""
        if pg_get is not None:
            try:
                raw = getter(spec.pg_key, None)
            except Exception:  # pragma: no cover — защитная ветка
                raw = None
            present = raw is not None
            value = str(raw or "")
        elif cache is not None:
            try:
                raw = cache.get(spec.pg_key, None)
                present = raw is not None
                value = str(raw or "")
            except Exception:      # pragma: no cover — PG down
                present = False
        if not present or not value.strip():
            continue
        reason, entry = provenance_state(spec, value, cache=cache)
        if reason == "attested":
            continue
        if value == factory_text(spec.block_id):
            # P0-PROMPTS: сохранённые байты уже равны текущей фабрике —
            # это не конфликт, ложный WARNING снят (identical_to_factory).
            continue
        classification = withheld_classification(spec.block_id, value)
        rows.append({
            "block_id": spec.block_id,
            "pg_key": spec.pg_key,
            "stored_sha256_12": sha12(value),
            "stored_chars": len(value),
            "stored_legacy_persona_marker": legacy_persona_present(value),
            "stored_known_canon": is_known_canon(value),
            "withheld_reason": reason,
            "withheld_class": (classification or {}).get(
                "class", WITHHELD_UNCLASSIFIED_CLASS),
            "withheld_class_reason": (classification or {}).get("reason", ""),
            "attested_revision": (str((entry or {}).get("revision") or "")
                                  or None),
            "factory_revision": factory_revision(spec.block_id),
            "family": spec.family,
        })
    return rows


def resolve_persisted_speech(pg_key: str, value: str,
                             *, source: str) -> str:
    """Effective-текст для persistend-значения (используется резолверами).

    Единая точка: любой резолвер (``prompt_style_blocks.resolve_prompt``,
    ``direct_chat_service``) обязан пропускать PG-значение через эту функцию,
    иначе речевой канон останется «виден только в Python».
    """
    return resolve_speech_value(pg_key, value, source=source).text


def resolve_hot_prompt(pg_key: str, value: str) -> tuple[str, str]:
    """``(effective, source)`` для значения из hot-слоя.

    ``source == "global"`` только если ключ реально ЕСТЬ в ПЕРСИСТЕНТНОМ слое
    (иначе это кодовый fallback → ``"default"``): именно так виден
    «фактический источник» (SOUL-AMD.3.2) без скрытой подмены.
    Провенанс (SOUL-AMD.1.2/4.6): незаписанное через API реестра значение
    канона старой личности удерживается → ``("default", ...)``.
    """
    source = "global" if _hot_present(pg_key) else "default"
    return resolve_hot_prompt_ex(pg_key, value, source=source)


def resolve_hot_prompt_ex(pg_key: str, value: str, *, source: str
                          ) -> tuple[str, str]:
    """``resolve_hot_prompt`` с явным источником (для вызывающих с диагностикой)."""
    resolved = resolve_speech_value(pg_key, value, source=source)
    return resolved.text, resolved.source


async def resolve_chat_speech(pg_key: str, code_default: str,
                              *, chat_id: int) -> tuple[str, str]:
    """Резолв базы канала как в рантайме: chat override → global → default.

    Возвращает ``(effective_text, source)``; ``source`` —
    ``chat|global|default`` (тот же словарь, что у
    ``prompt_composer.resolve_base_source``). Подавление legacy-сегментов
    применяется только к ПЕРСИСТЕНТНЫМ значениям (см. модульный docstring);
    незаписанные через API реестра значения канонов старой личности
    удерживаются (провенанс, §1.2/§4.6) — source тогда ``default``.
    """
    resolved = await resolve_chat_speech_ex(pg_key, code_default,
                                            chat_id=chat_id)
    return resolved.text, resolved.source


async def resolve_chat_speech_ex(pg_key: str, code_default: str,
                                 *, chat_id: int) -> SpeechResolution:
    """``resolve_chat_speech`` с диагностикой удержания (провенанс)."""
    from services import hot_config as hot
    default_value = hot.get(pg_key, code_default)
    value = default_value
    source = "default"
    try:
        from services.chat_params import get_chat_param as _cpg
        value = await _cpg(chat_id, pg_key, default_value)
    except Exception:          # pragma: no cover — PG down → глобальный слой
        value = default_value
    if await _chat_present(chat_id, pg_key):
        source = "chat"
    elif _hot_present(pg_key):
        source = "global"
    text = str(value) if isinstance(value, str) else str(code_default)
    if not text.strip():
        text, source = str(code_default), "default"
    return resolve_speech_value(pg_key, text, source=source)


__all__ = [
    "REGISTRY_VERSION", "PromptBlockSpec", "EffectivePrompt",
    "LegacySuppression", "SpeechResolution", "FACTORY_SET_SHA256_12",
    "LEGACY_PERSONA_RULES", "PROVENANCE_DOC_KEY", "PROVENANCE_MAP_FIELD",
    "PROVENANCE_WRITE_KINDS",
    "CORE_DOC_KEY", "CORE_FULL_BLOCK_ID", "CORE_COMPACT_BLOCK_ID",
    "CORE_DETAIL_LEVELS", "CORE_DETAIL_REASONS", "CORE_SOURCE",
    "core_selection", "core_selection_view", "core_active_revision",
    "doc_field_text",
    "all_blocks", "block", "block_for", "by_pg_key", "speech_blocks",
    "legacy_persona_blocks", "unregistered_catalog_keys", "reset_cache",
    "factory_text", "factory_default", "factory_revision", "factory_texts",
    "factory_set_fingerprint", "production_kind", "effective_prompt",
    "registry_view", "suppress_legacy_speech", "known_canon_hashes",
    "CFG07A_PAYLOAD_CLEAN_KEYS", "payload_custom_clean_scope",
    "is_known_canon", "legacy_persona_present", "resolve_persisted_speech",
    "resolve_chat_speech", "resolve_chat_speech_ex", "resolve_hot_prompt_ex",
    "resolve_speech_value", "withholding_required", "withholding_blocks",
    "PROVENANCE_EXEMPT_PREFIXES",
    "provenance_doc", "attested_revision", "provenance_state",
    "withheld_values", "sha12",
]
