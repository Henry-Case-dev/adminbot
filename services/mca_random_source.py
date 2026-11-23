"""mca-10a (`mca-10a-random-source-anu`, ADR-1028-14 D1–D5, spec §2–§7) —
единственный контур поведенческой случайности: RandomSource (quantum |
pseudorandom), ANU-клиент, политика exploration, durable-запас/refill,
журнал draw, квота, честная активация и fallback.

Границы (вторые механизмы запрещены):
  * один сервис: `RandomSourceService` (async) + `ExplorationPolicy`
    (чистая логика + инъекция источника) + `CoreDreamRandomSource`
    (sync-адаптер стыка mca-06) + `AnuClient` (async) + `LfdrClient`
    (async, публичный QRNG без ключа) + `RandomStore`
    (v27-таблицы через `write_transaction`/DatabaseService);
  * события — только единый `emit_mca_event` (`mca_events`, компонент
    `random`, notable-only); second словарь/канал не создаётся;
  * запись — только общий write-механизм mca-01 (`write_transaction`);
  * фоновая задача refill — существующий `TaskSupervisor`/`task_jobs`
    (`owner="random.source"`, `coalesce_key="random.refill:<account>"`).

Инварианты (spec/ADR):
  * selected (настройка `memory.random_source`) ≠ effective (резолвится на
    каждом draw); режим переживает рестарты (bot_settings);
  * `fallback_to_pseudorandom` — пользовательская настройка, НЕ kill-switch;
  * rejection sampling `limit=(range//n)*n`, без modulo bias; n=1 — draw не
    расходуется; каждый draw — отдельное значение;
  * PRNG — stdlib `random.Random` (auto-seed; `randrange`/`random()`),
    реализация/версия фиксируются для диагностики; НЕ для ключей/токенов/
    security; своя криптография не пишется;
  * «выбор ≠ вердикт»: случайность выбирает материал/альтернативу, не
    истинность/права/уместность; недопустимые измерения не рандомизируются;
  * ANU-ключ никогда не попадает в логи/URL/события/таблицы (в v27 — только
    `key_fingerprint = sha256(key)[:12]`, сервер-only);
  * OFF-паритет: K1 OFF → ровно `mca_dream_random.default_source`; K2 OFF →
    ANU-запросов нет; K3 OFF → refill не запускается; K4 OFF → политика
    возвращает primary без probability-draw; каждый OFF = поведение 2.58.57
    для своего пути.

Kill-switches/env-лимиты (D11): `MCA_RANDOM_SOURCE_ENABLED`,
`MCA_RANDOM_QUANTUM_ENABLED`, `MCA_RANDOM_REFILL_ENABLED`,
`MCA_RANDOM_EXPLORATION_ENABLED` (default ON) + env-only
`MCA_RANDOM_CIRCUIT_FAILS`/`..._COOLDOWN_SECONDS`/`..._MIN_REQUEST_INTERVAL_
SECONDS`/`..._DRAW_RETENTION_DAYS`/`..._DRAW_MAX_ROWS`/`..._ANU_TRIAL_
MONTHLY_LIMIT`/`..._ANU_TRIAL_RPS`/`..._QUANTUM_HEX_BLOCK_SIZE` — резолв
per-call через `services.mca_gates` (никогда не бросает).
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import importlib.util
import json
import logging
import platform
import random
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from config.settings import APP_VERSION, settings
from services import mca_dream_random, mca_events, mca_gates

logger = logging.getLogger(__name__)

# ── режимы/источники ────────────────────────────────────────────────────────
MODE_QUANTUM = "quantum"
MODE_PSEUDORANDOM = "pseudorandom"
MODES = (MODE_QUANTUM, MODE_PSEUDORANDOM)

SOURCE_IMPL_PRNG = "python-random-mt19937"
# Легаси-значение provider в durable-истории (`mca_random_batches`/
# `mca_random_draws`). История НЕ переписывается (arch P1 D1/D2); новые
# записи идут с каноническим id `PROVIDER_ID_ANU`, а чтение маппит легаси
# через `canonical_provider_id()`.
PROVIDER_ANU = "ANU Quantum Numbers"
PROVIDER_PRNG = "python-random"

# Purpose (закрытый набор 10a; расширение имён — санкция 10b).
PURPOSE_LESS_STUDIED = mca_dream_random.PURPOSE_LESS_STUDIED
PURPOSE_ACTIVATION_SELFCHECK = "activation_selfcheck"
PURPOSE_SLEEP_CONSOLIDATION = "sleep_after_consolidation"
# mca-10b (ADR-1028-17 D2/AM-1, санкция spec §13): санкционированное
# расширение закрытого набора ровно на 5 purpose. НОВЫХ probability-ключей
# нет — карта связывает purpose с существующими двумя гейтами (разговор /
# после сна); `ui_replay`/`ui_visualization` — НЕ purposes (read-only
# маркер/настройка; `choose()` отвергает неизвестный purpose).
PURPOSE_CONVERSATION_VARIANT = "conversation_variant"
PURPOSE_MEMORY_RECALL = "memory_recall"
PURPOSE_ARCHIVE_SAMPLE = "archive_sample"
PURPOSE_BELIEF_REVIEW = "belief_review"
PURPOSE_ASSOCIATION_PAIR = "association_pair"
# EVOL-014: санкционированное расширение закрытого набора — триггер
# инициативного мема. Это НЕ exploration-выбор альтернативы (choose()
# по-прежнему отвергает purpose вне EXPLORATION_PURPOSES) и НЕ новый
# probability-ключ. Draw идёт через draw_probability; недоступность
# контура потребитель фиксирует как random_unavailable, без локального
# Math.random / random.Random.
PURPOSE_MEME_TRIGGER = "meme_trigger"
# QND-NONDET §4 (owner corrective 2026-11-10): санкционированное расширение
# закрытого набора — четыре purpose квантовой недетерминистики. Два
# расписания смысловой проверки (`<механизм>_schedule`) и два решения о
# публикации (`<механизм>_publication`). Второго клиента/генератора нет —
# тот же `RandomSourceService`; probability-ключей карты exploration здесь нет
# (порог задаёт модель §3 контракта / `limits.qnd_*`).
PURPOSE_NOSTALGIA_SCHEDULE = "nostalgia_schedule"
PURPOSE_INITIATIVE_SCHEDULE = "initiative_schedule"
PURPOSE_NOSTALGIA_PUBLICATION = "nostalgia_publication"
PURPOSE_INITIATIVE_PUBLICATION = "initiative_publication"
# INIT-COORD `initiative_trigger` ВЫВЕДЕН (контракт §4/§6(e)): вероятностный
# гейт ПЕРЕД оценкой заменён решением после оценки (§3). Имя оставлено
# импорт-совместимым, но НЕ санкционировано: draw с этим purpose больше не
# делается ни одним потребителем.
PURPOSE_INITIATIVE_TRIGGER_RETIRED = "initiative_trigger"
PURPOSE_INITIATIVE_TRIGGER = PURPOSE_INITIATIVE_TRIGGER_RETIRED

# purpose → ключ вероятности (одна карта в одном месте; D6).
EXPLORATION_PROBABILITY_KEYS = {
    PURPOSE_LESS_STUDIED: "memory.random_exploration_probability",
    PURPOSE_SLEEP_CONSOLIDATION: "memory.random_sleep_exploration_probability",
    PURPOSE_CONVERSATION_VARIANT: "memory.random_exploration_probability",
    PURPOSE_MEMORY_RECALL: "memory.random_exploration_probability",
    PURPOSE_ARCHIVE_SAMPLE: "memory.random_sleep_exploration_probability",
    PURPOSE_BELIEF_REVIEW: "memory.random_sleep_exploration_probability",
    PURPOSE_ASSOCIATION_PAIR: "memory.random_sleep_exploration_probability",
}
EXPLORATION_PURPOSES = frozenset(EXPLORATION_PROBABILITY_KEYS)
INTERNAL_PURPOSES = frozenset({PURPOSE_ACTIVATION_SELFCHECK})
# Draw-purpose, которые контур принимает как санкционированные. Мем-триггер
# здесь, но не в карте exploration: это не выбор альтернативы. QND-NONDET
# (§4): расписание/публикация обоих механизмов — тоже draw-purpose, но не
# выбор альтернативы (поэтому не в EXPLORATION_PURPOSES).
SANCTIONED_DRAW_PURPOSES = (
    EXPLORATION_PURPOSES | INTERNAL_PURPOSES
    | frozenset({
        PURPOSE_MEME_TRIGGER,
        PURPOSE_NOSTALGIA_SCHEDULE, PURPOSE_INITIATIVE_SCHEDULE,
        PURPOSE_NOSTALGIA_PUBLICATION, PURPOSE_INITIATIVE_PUBLICATION,
    })
)


def purpose_sanctioned(purpose: str) -> bool:
    """True, если purpose входит в закрытый санкционированный набор."""
    return str(purpose or "") in SANCTIONED_DRAW_PURPOSES

# Недопустимые измерения (D6/T-4967): не рандомизируются никогда. Координатор
# формирует только допустимые альтернативы; политика дополнительно отвергает
# явно объявленное недопустимое измерение с причиной `no_eligible_alternative`.
INELIGIBLE_MEASUREMENTS = frozenset({
    "truth", "identity", "source_assignment", "rights", "deletion",
    "direct_request", "financial_settings",
})

POLICY_VERSION = "mca10a-v1"
CANDIDATES_CAP = 50
SELECTION_META_CAP = 200
MAX_DRAW_ATTEMPTS = 32
JOURNAL_QUEUE_MAX = 256
DREAM_CHUNK_MIN = 8
DREAM_CHUNK_MAX = 64

# Настройки (pg_key; блок C добавляет каталог; рантайм читает через
# существующий read-path и fail-open на дефолт).
SETTING_SOURCE = "memory.random_source"
SETTING_FALLBACK = "memory.random_fallback_to_pseudorandom"
SETTING_EXPLORATION = "memory.random_exploration_probability"
SETTING_SLEEP_EXPLORATION = "memory.random_sleep_exploration_probability"
SETTING_KEY = "keys.random_quantum_api_key"
SETTING_ENDPOINT = "keys.random_quantum_endpoint"
SETTING_PLAN = "keys.random_quantum_plan"
SETTING_BATCH_LENGTH = "keys.random_quantum_batch_length"
SETTING_DATA_TYPE = "keys.random_quantum_data_type"
SETTING_TIMEOUT = "keys.random_quantum_request_timeout_seconds"
SETTING_LOW_WATERMARK = "keys.random_quantum_refill_low_watermark"
SETTING_BUFFER_MAX = "keys.random_quantum_buffer_max_values"

# ── QRNG P5: IBM Quantum Platform (QAN-REC-IBM-01…03) ──────────────────────
# Аккаунт канала `ibm_quantum_platform`: API key и CRN — РАЗДЕЛЬНЫЕ
# защищённые серверные поля (global admin); instance/region/channel —
# несекретные настройки подключения. Plan не хранится как заявленное
# значение: он читается из фактического ответа IBM (status/usage), а при
# отсутствии данных честно `None`.
SETTING_IBM_KEY = "keys.random_ibm_api_key"
SETTING_IBM_CRN = "keys.random_ibm_crn"
SETTING_IBM_INSTANCE = "keys.random_ibm_instance"
SETTING_IBM_REGION = "keys.random_ibm_region"
SETTING_IBM_CHANNEL = "keys.random_ibm_channel"
# Пороги/лимиты Open Plan — те же существующие durable-строки task_jobs,
# без нового планировщика/таблицы. Все значения — PG-only (global admin).
SETTING_IBM_HTTP_TIMEOUT = "random.ibm.http_timeout_seconds"
SETTING_IBM_POLL_INTERVAL = "random.ibm.poll_interval_seconds"
SETTING_IBM_JOB_MAX_AGE = "random.ibm.job_max_age_seconds"
SETTING_IBM_MAX_INFLIGHT = "random.ibm.max_inflight"
SETTING_IBM_MAX_JOBS_PER_DAY = "random.ibm.max_jobs_per_day"
SETTING_IBM_MAX_QPU_SECONDS_PER_DAY = "random.ibm.max_qpu_seconds_per_day"

IBM_CHANNEL = "ibm_quantum_platform"
IBM_INSTANCE_DEFAULT = "open-instance"
IBM_REGION_DEFAULT = "us-east"
IBM_MIN_QUBITS = 16
IBM_SMOKE_SHOTS = 256
IBM_MIN_SHOTS = 256
IBM_MAX_SHOTS = 20000
IBM_JOB_KIND = "random.ibm_job"
IBM_JOB_OWNER = "random.source"
IBM_JOB_PENDING = "pending"
IBM_JOB_SUBMITTED = "submitted"
IBM_JOB_QUEUED = "queued"
IBM_JOB_RUNNING = "running"
IBM_JOB_COMPLETED = "completed"
IBM_JOB_FAILED = "failed"
IBM_JOB_CANCELLED = "cancelled"
IBM_JOB_EXPIRED = "expired"
DEFAULT_IBM_HTTP_TIMEOUT_SECONDS = 10
DEFAULT_IBM_POLL_INTERVAL_SECONDS = 30
DEFAULT_IBM_JOB_MAX_AGE_SECONDS = 3600
DEFAULT_IBM_MAX_INFLIGHT = 1
# Open Plan — реальный расход ограничен владельцем (bounded jobs/RU), но не
# превращён в постоянный OFF: готовый адаптер работает при наличии полей.
DEFAULT_IBM_MAX_JOBS_PER_DAY = 4
DEFAULT_IBM_MAX_QPU_SECONDS_PER_DAY = 120

DEFAULT_SOURCE = MODE_QUANTUM
# QRNG P3/F3 (arch D6): заводской дефолт «честного» PRNG-отката для НОВЫХ
# установок — выключен. Сохранённое `true` владельца (прод) не перезаписывается:
# значение читается из bot_settings/chat_params, дефолт применяется только при
# отсутствии явной настройки. Параметр существующий — Settings-поле и сид
# (INSERT ... ON CONFLICT DO NOTHING) получают false, существующая строка цела.
DEFAULT_FALLBACK = False
DEFAULT_EXPLORATION_PROBABILITY = 0.05
DEFAULT_BATCH_LENGTH = 1024
DEFAULT_DATA_TYPE = "uint16"
DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_LOW_WATERMARK = 256
DEFAULT_BUFFER_MAX = 2048
DEFAULT_PLAN = "Trial"
PLANS = ("Trial", "Paid", "Custom")

# ── QRNG-реестр провайдеров (P1; arch D1 `QAN-REC-REG-01`) ──────────────────
# Модульный словарь внутри ЭТОГО сервиса: второй сервис/слой не создаётся.
# Ровно три записи; снятый владельцем провайдер (owner_inputs 2026-11-17,
# `QAN-REC-EXC-01…05`) отсутствует — ни адаптера, ни id, ни ветки
# совместимости. `entropy_class` — производное от провайдера значение (в БД
# колонкой не дублируется, отдаётся в DTO). P2 подключает адаптер LfDR
# (`LfdrClient` + точки входа `lfdr_fetch`/`lfdr_check` — ниже, после класса);
# P5 подключает IBM (`IbmQuantumRuntimeClient` + `ibm_fetch`/`ibm_check`):
# реальный QPU Sampler, чтение/измерения разделены, симулятор отвергается.
ENTROPY_CLASS_HARDWARE = "hardware_quantum"
PROVIDER_ID_IBM = "ibm_quantum"
PROVIDER_ID_ANU = "anu"
PROVIDER_ID_LFDR = "lfdr"
PROVIDER_IDS = (PROVIDER_ID_IBM, PROVIDER_ID_ANU, PROVIDER_ID_LFDR)


@dataclass(frozen=True)
class ProviderSpec:
    """Запись реестра провайдеров (D1): без поведения и без секретов.

    `fetch`/`check` — точки подключения адаптеров (P2/P5); `None` до них.
    `key_setting` — pg-ключ секрета или `None`, если ключ не требуется."""

    id: str
    title: str
    entropy_class: str = ENTROPY_CLASS_HARDWARE
    requires_key: bool = True
    key_setting: str | None = None
    docs_url: str = ""
    fetch: Callable | None = None
    check: Callable | None = None


PROVIDERS: dict[str, ProviderSpec] = {
    PROVIDER_ID_IBM: ProviderSpec(
        id=PROVIDER_ID_IBM, title="IBM Quantum",
        key_setting=SETTING_IBM_KEY,
        docs_url="https://quantum.cloud.ibm.com"),
    PROVIDER_ID_ANU: ProviderSpec(
        id=PROVIDER_ID_ANU, title="ANU Quantum Numbers",
        key_setting=SETTING_KEY,
        docs_url="https://quantumnumbers.anu.edu.au"),
    PROVIDER_ID_LFDR: ProviderSpec(
        id=PROVIDER_ID_LFDR, title="LfDR QRNG",
        requires_key=False, docs_url="https://lfdr.de/QRNG/"),
}

# Легаси/человекочитаемые имена → канонический id (чтение; запись не
# переписывается). Неизвестное имя НЕ подменяется молча: `""`.
_PROVIDER_ALIASES = {
    "anu quantum numbers": PROVIDER_ID_ANU,
    "anu": PROVIDER_ID_ANU,
    "ibm quantum": PROVIDER_ID_IBM,
    "ibm_quantum": PROVIDER_ID_IBM,
    "lfdr": PROVIDER_ID_LFDR,
    "lfdr qrng": PROVIDER_ID_LFDR,
}

# Все 9 ключей подключения провайдера (P1: операции с ними — только global
# admin, arch D8/`RBAC-01/02`; `keys.random_quantum_provider` — информационное
# имя, P3 скроет его из UI).
SETTING_PROVIDER_INFO = "keys.random_quantum_provider"
PROVIDER_KEY_SETTINGS = (
    SETTING_PROVIDER_INFO, SETTING_KEY, SETTING_ENDPOINT, SETTING_PLAN,
    SETTING_BATCH_LENGTH, SETTING_DATA_TYPE, SETTING_TIMEOUT,
    SETTING_LOW_WATERMARK, SETTING_BUFFER_MAX,
)
# Провайдеры, чьи durable-партии принадлежат ANU-ключу (backfill P1 D2 +
# фильтр расходования). Оба написания: история + каноническая запись.
ANU_PROVIDER_IDS = (PROVIDER_ID_ANU, PROVIDER_ANU)

# ── QRNG P3: селектор провайдера/fallback (arch D4/D5/D6) ──────────────────
# ГЛОБАЛЬНЫЕ настройки (категория memory + global_only в каталоге): чатовый
# override невозможен (POST chat-scope → 422), чатовый админ их не видит.
# PRNG — НЕ провайдер и НЕ элемент fallback_order: только явный режим
# `memory.random_source=pseudorandom` либо явный переключатель
# `memory.random_fallback_to_pseudorandom` (ниже, без дублирования).
SETTING_PRIMARY_PROVIDER = "random.primary_provider"
SETTING_PROVIDER_FALLBACK_ENABLED = "random.fallback_enabled"
SETTING_FALLBACK_ORDER = "random.fallback_order"
# F1 (D4): три глобальных ключа селектора. В chat-scope GET /api/config их
# видит только global admin (чатовый админ — нет); запись уже 422 (global_only).
SELECTOR_SETTING_KEYS = (SETTING_PRIMARY_PROVIDER,
                         SETTING_PROVIDER_FALLBACK_ENABLED,
                         SETTING_FALLBACK_ORDER)

DEFAULT_PRIMARY_PROVIDER = PROVIDER_ID_IBM
# Заводской запасной порядок — относительно primary по умолчанию (IBM):
# ANU, затем публичный LfDR. Примиривается с выбранным primary при чтении
# (сам primary из порядка исключается — см. effective_order()).
DEFAULT_FALLBACK_ORDER = (PROVIDER_ID_ANU, PROVIDER_ID_LFDR)
DEFAULT_PROVIDER_FALLBACK_ENABLED = True

# Состояние сохранённого значения primary (arch D5/EXC-03):
#   absent              — строки нет, действует заводской default;
#   set                 — известный id реестра (включая читаемый легаси-алиас);
#   requires_resolution — значение вне действующего контракта (снятый
#                         провайдер/неизвестный id): НЕ действует, НЕ
#                         подменяется молча, НЕ перезаписывается.
PRIMARY_SETTING_ABSENT = "absent"
PRIMARY_SETTING_SET = "set"
PRIMARY_SETTING_REQUIRES_RESOLUTION = "requires_resolution"

# Канонический порядок разрешения снятого значения (arch D5, EXC-03):
# ровно три действующих провайдера, IBM → ANU → LfDR.
CANONICAL_PROVIDER_ORDER = (PROVIDER_ID_IBM, PROVIDER_ID_ANU, PROVIDER_ID_LFDR)

# Исторические написания provider в durable-партиях каждого канонического id
# (фильтр reserve_draw/reserve_chunk; история не переписывается).
PROVIDER_STORAGE_IDS: dict[str, tuple[str, ...]] = {
    PROVIDER_ID_IBM: (PROVIDER_ID_IBM,),
    PROVIDER_ID_ANU: ANU_PROVIDER_IDS,
    PROVIDER_ID_LFDR: (PROVIDER_ID_LFDR,),
}


def canonical_provider_id(value) -> str:
    """Канонический id провайдера или `""` (неизвестное не подменяется)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text in PROVIDERS:
        return text
    return _PROVIDER_ALIASES.get(text.lower(), "")


def entropy_class_for(provider_id) -> str | None:
    """`entropy_class` провайдера (все три — `hardware_quantum`); иначе None."""
    spec = PROVIDERS.get(str(provider_id or ""))
    return spec.entropy_class if spec is not None else None


def source_impl_for(provider_id) -> str:
    """`source_impl` квантового пути — производное от провайдера, не хардкод.

    ANU → `"anu-quantum"` (совместимо с историей), IBM → `"ibm-quantum"`,
    неизвестный → `"quantum"`."""
    pid = str(provider_id or "")
    if pid == PROVIDER_ID_IBM:
        return "ibm-quantum"
    return f"{pid}-quantum" if pid else "quantum"


def config_matches(batch_fingerprint, current_fingerprint) -> bool:
    """Совместима ли партия с действующей конфигурацией (F4 strict).

    NULL-партия (легаси/без привязки) — совместима; партия с отпечатком —
    только при непустом совпадающем текущем. Пустой текущий (ключа нет) НЕ
    делает партии старого ключа совместимыми."""
    bf = str(batch_fingerprint or "").strip()
    cf = str(current_fingerprint or "").strip()
    if not bf:
        return True
    return bool(cf) and bf == cf


def primary_setting_state(raw) -> str:
    """Состояние сохранённого `random.primary_provider` (D5/EXC-03).

    Неизвестный/снятый id НЕ действует и НЕ подменяется молча: состояние
    `requires_resolution`, значение остаётся как сохранено."""
    text = str(raw or "").strip()
    if not text:
        return PRIMARY_SETTING_ABSENT
    return (PRIMARY_SETTING_SET if canonical_provider_id(text)
            else PRIMARY_SETTING_REQUIRES_RESOLUTION)


def normalize_fallback_order(raw) -> list[str]:
    """Сохранённый `random.fallback_order` → список канонических id реестра.

    Чтение защитное: неизвестные id/не-строки/дубли отбрасываются (значение
    в БД НЕ переписывается), чтобы повреждённая строка не ломала резолв.
    Строка JSON-текста (двойное кодирование jsonb) распаковывается."""
    value = raw
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        pid = canonical_provider_id(item)
        if pid and pid not in out:
            out.append(pid)
    return out


def fallback_order_state(raw) -> str:
    """Состояние сохранённого `random.fallback_order` (без перезаписи).

    `absent` — строки нет (действует заводской порядок); `set` — корректный
    список канонических id; `requires_resolution` — сохранённое значение не
    соответствует контракту (неизвестный id/дубль/не список) и не действует
    как есть — резолв применяет защитную нормализацию, значение остаётся."""
    if raw is None:
        return PRIMARY_SETTING_ABSENT
    value = raw
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return PRIMARY_SETTING_REQUIRES_RESOLUTION
    if not isinstance(value, (list, tuple)):
        return PRIMARY_SETTING_REQUIRES_RESOLUTION
    if any(not isinstance(item, str) or item not in PROVIDERS
           for item in value):
        return PRIMARY_SETTING_REQUIRES_RESOLUTION
    if len(set(value)) != len(value):
        return PRIMARY_SETTING_REQUIRES_RESOLUTION
    if len(value) > len(PROVIDER_IDS):
        return PRIMARY_SETTING_REQUIRES_RESOLUTION
    return PRIMARY_SETTING_SET


def build_effective_order(primary: str | None, order,
                          fallback_enabled: bool) -> tuple[str, ...]:
    """Действующий порядок провайдеров (D5): primary → fallback_order.

    `primary` — канонический id либо None (снятое/неизвестное значение:
    действует КАНОНИЧЕСКИЙ порядок IBM→ANU→LfDR, arch P3/EXC-03). Сохранённый
    fallback_order при снятом primary не применяется (он был построен под
    недействительную настройку). Дубли и сам primary из хвоста исключаются;
    при выключенном fallback остаётся только primary."""
    tail = list(order or ())
    if primary is None:
        if not fallback_enabled:
            return (DEFAULT_PRIMARY_PROVIDER,)
        return tuple(CANONICAL_PROVIDER_ORDER)
    if not fallback_enabled:
        return (primary,)
    head = [primary]
    for pid in tail:
        if pid != primary and pid not in head:
            head.append(pid)
    return tuple(head)


# ANU-контракт §14.3 (endpoint/header/defaults предзаполнены; owner вводит
# только ключ).
ANU_HOST = "api.quantumnumbers.anu.edu.au"
ANU_ENDPOINT = f"https://{ANU_HOST}"
ANU_HEADER = "x-api-key"
DATA_TYPES = frozenset({"uint8", "uint16", "hex8", "hex16"})
HEX_TYPES = frozenset({"hex8", "hex16"})
UINT_RANGES = {"uint8": 256, "uint16": 65536}
MIN_LENGTH = 1
MAX_LENGTH = 1024
MIN_HEX_SIZE = 1
MAX_HEX_SIZE = 10

# ANU-состояния (D9-контракт для витрины; выводится из mca_random_state).
ANU_STATE_DISABLED = "disabled"
ANU_STATE_UNCONFIGURED = "provider_unconfigured"
ANU_STATE_UNVERIFIED = "unverified"
ANU_STATE_ACTIVE = "active"
ANU_STATE_DEGRADED = "degraded"
ANU_STATE_QUOTA = "quota_exhausted"
_DEGRADED_REASONS = frozenset({
    "provider_unavailable", "auth_failed", "timeout", "validation_failed",
    "delivery_unknown", "rate_limit", "redirect_blocked", "client_error",
})
# Причины, при которых повторный запрос ANU в refill заведомо не изменит
# исход (неверный ключ/исчерпанная месячная квота). Транзиентные 5xx/timeout
# сюда НЕ входят: их ограничивает breaker, а не постоянный skip.
ANU_STATE_PERSISTENT_BLOCKERS = frozenset({"auth_failed", "quota_exhausted"})


def _utc_period(now: float | None = None) -> str:
    """Период квоты `YYYY-MM` (UTC; account-global, не per-chat)."""
    ts = float(now if now is not None else time.time())
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def key_fingerprint(key: str) -> str:
    """Сервер-only детектор смены ключа: `sha256(key)[:12]` (НЕ ключ)."""
    try:
        return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:12]
    except Exception:      # pragma: no cover - защитная ветка
        return ""


def map_value_to_index(value: int, n: int, value_range: int) -> int | None:
    """Rejection sampling `limit=(range//n)*n` (без modulo bias).

    `None` — значение отвергнуто (или диапазон меньше n — честный отказ,
    без тихой подмены). `n == 1` → 0 (вызывающий не расходует draw)."""
    try:
        n = int(n)
        value = int(value)
        value_range = int(value_range)
    except (TypeError, ValueError):
        return None
    if n <= 0 or value_range <= 0:
        return None
    if n == 1:
        return 0
    limit = (value_range // n) * n
    if limit <= 0 or value < 0 or value >= value_range:
        return None
    if value >= limit:
        return None
    return value % n


def batch_value_range(data_type: str, values) -> int:
    """Диапазон значений партии для rejection sampling.

    uint8/uint16 — точный power-of-two диапазон. hex8/hex16 — консервативный
    power-of-two по максимальному значению партии (≤ фактического диапазона;
    для uniform-партии из 1024 значений совпадает с точным с вероятностью
    1 − 2^-1024; меньший диапазон статистически безопасен — только больше
    отказов, без bias)."""
    if data_type in UINT_RANGES:
        return UINT_RANGES[data_type]
    try:
        top = max(int(v) for v in values)
    except Exception:
        return 0
    return 1 << max(1, top.bit_length())


def _candidate_id(candidate) -> str:
    """ID кандидата для журнала (R17-safe: только идентификаторы)."""
    if isinstance(candidate, dict):
        raw = candidate.get("id")
    else:
        raw = getattr(candidate, "id", None)
    if raw is None:
        raw = candidate if isinstance(candidate, (str, int)) else None
    return str(raw)[:120] if raw is not None else ""


def _same_candidate(a, b) -> bool:
    """Сравнение «тот же основной» для пула без основного (identity/ID)."""
    if a is b:
        return True
    try:
        if a == b:
            return True
    except Exception:
        pass
    ca, cb = _candidate_id(a), _candidate_id(b)
    return bool(ca) and ca == cb


# ── ошибки/партии ANU ───────────────────────────────────────────────────────
class AnuError(Exception):
    """Ошибка ANU-контура: код (reason_code), очищенная причина, sent.

    `sent=True` ⇔ запрос реально ушёл на сервер (квота могла быть израсходована;
    таймаут после отправки учитывается как `unknown`, не success/failed).
    `reason` — R17-safe (ключ замаскирован), в логи/события не попадает сырым."""

    def __init__(self, code: str, reason: str = "", *, retryable: bool = False,
                 sent: bool = False, retry_after: int | None = None) -> None:
        self.code = str(code)
        self.reason = str(reason)[:160]
        self.retryable = bool(retryable)
        self.sent = bool(sent)
        self.retry_after = retry_after
        super().__init__(f"code={self.code} | reason={self.reason}")


@dataclass
class AnuBatch:
    """Валидная партия реальных чисел ANU (после schema/тип/диапазон/длина).

    `provider` — канонический id (`anu`) для НОВЫХ записей; легаси-строка
    `"ANU Quantum Numbers"` остаётся читаемой через `canonical_provider_id()`."""

    values: list
    data_type: str
    length: int
    provider: str = PROVIDER_ID_ANU
    latency_ms: int | None = None
    # Реальное происхождение партии (IBM P5): job/backend/shots/bits/usage.
    # Поле аддитивное: ANU/LfDR оставляют None, существующие потребители не
    # меняются. Секретов (API key/полный CRN) здесь нет по построению.
    provenance: dict | None = None


@dataclass
class _HttpResponse:
    status: int
    headers: dict
    text: str


def validate_endpoint(url: str) -> str:
    """Origin-guard ANU (не SSRF): только https + точный host + без
    userinfo/порта/пути/query. Иное → `scheme_not_allowed`/`invalid_url`
    (коды mca-02), запрос не выполняется, ключ не отправляется."""
    raw = str(url or "").strip()
    if not raw:
        raise AnuError("invalid_url", "empty endpoint", sent=False)
    try:
        parts = urlsplit(raw)
    except Exception:
        raise AnuError("invalid_url", "unparsable endpoint", sent=False)
    if parts.scheme.lower() != "https":
        raise AnuError("scheme_not_allowed",
                       f"scheme={parts.scheme or 'none'}", sent=False)
    if parts.username or parts.password:
        raise AnuError("invalid_url", "userinfo not allowed", sent=False)
    host = (parts.hostname or "").lower()
    if host != ANU_HOST:
        raise AnuError("invalid_url", f"host not allowed: {host}", sent=False)
    try:
        port = parts.port
    except ValueError:
        raise AnuError("invalid_url", "bad port", sent=False)
    if port not in (None, 443):
        raise AnuError("invalid_url", "port not allowed", sent=False)
    if (parts.path or "") not in ("", "/"):
        raise AnuError("invalid_url", "path not allowed", sent=False)
    if parts.query or parts.fragment:
        raise AnuError("invalid_url", "query/fragment not allowed", sent=False)
    return ANU_ENDPOINT


def _parse_retry_after(headers) -> int | None:
    raw = None
    try:
        for k, v in (headers or {}).items():
            if str(k).lower() == "retry-after":
                raw = v
                break
    except Exception:
        raw = None
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return max(0, min(seconds, 3600))


def _clean_error_text(raw, key: str = "") -> str:
    """Очистить error-поле провайдера: маска ключа + sanitize + bound."""
    text = str(raw or "").replace("\n", " ").replace("\r", " ").strip()
    if key and key in text:
        text = text.replace(key, "***")
    try:
        from services.log_ring import sanitize
        text = sanitize(text)
    except Exception:
        pass
    return text[:160] or "provider error"


async def _default_http_get(url: str, headers: dict, params: dict,
                            timeout: float) -> _HttpResponse:
    """Дефолтный GET через httpx: TLS-верификация по умолчанию,
    `follow_redirects=False` (ключ не уходит по redirect)."""
    import httpx
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        resp = await client.get(url, headers=headers, params=params)
        return _HttpResponse(
            status=int(resp.status_code),
            headers={str(k).lower(): v for k, v in resp.headers.items()},
            text=resp.text)


class AnuClient:
    """Клиент ANU (доверенный провайдер; SafeFetcher не дублируется).

    Контракт §14.3: GET `https://api.quantumnumbers.anu.edu.au`, header
    `x-api-key`, query `length` 1–1024, `type` uint8/uint16/hex8/hex16,
    `size` только для hex (1–10). Валидация HTTPS/TLS/JSON/schema/success/
    типа/диапазона/длины. Таймаут; backoff с учётом Retry-After; circuit
    breaker (3 fails → open на 60 c → half-open один probe); 401/403 →
    `auth_failed` без цикла; 429 → `quota_exhausted` без запроса на каждое
    сообщение (min interval). In-memory (рестарт допустим; последняя причина
    durable в `mca_random_state`). Ключ не логируется и не попадает в URL."""

    def __init__(self, *, http_get: Callable | None = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 min_interval: float = 1.0, circuit_fails: int = 3,
                 circuit_cooldown: float = 60.0, clock: Callable | None = None
                 ) -> None:
        self._http_get = http_get or _default_http_get
        self._timeout = float(timeout)
        self._min_interval = float(min_interval)
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = float(circuit_cooldown)
        self._clock = clock or time.monotonic
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._last_request_at: float | None = None
        self._next_allowed_at = 0.0

    # ── конфигурация (hot-значения читает сервис per-call) ─────────────────
    def configure(self, *, timeout: float, min_interval: float,
                  circuit_fails: int, circuit_cooldown: float) -> None:
        self._timeout = float(timeout)
        self._min_interval = max(0.0, float(min_interval))
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = max(1.0, float(circuit_cooldown))

    def status(self) -> dict:
        return {
            "fails": int(self._fails),
            "circuit_open_until": float(self._open_until),
            "next_allowed_at": float(self._next_allowed_at),
            "last_request_at": self._last_request_at,
        }

    def available(self) -> bool:
        now = self._clock()
        return now >= self._open_until and now >= self._next_allowed_at

    # ── breaker/backoff ────────────────────────────────────────────────────
    def _note_failure(self, now: float, retry_after: int | None) -> None:
        self._fails += 1
        backoff = min(self._cooldown, float(2 ** min(self._fails, 6)))
        if retry_after:
            backoff = max(backoff, float(retry_after))
        self._next_allowed_at = now + backoff
        if self._fails >= self._circuit_fails:
            self._open_until = now + self._cooldown
            self._probe_used = False

    def _note_success(self) -> None:
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._next_allowed_at = 0.0

    # ── fetch ──────────────────────────────────────────────────────────────
    async def fetch(self, *, key: str, length: int = DEFAULT_BATCH_LENGTH,
                    data_type: str = DEFAULT_DATA_TYPE,
                    endpoint: str = ANU_ENDPOINT,
                    size: int | None = None) -> AnuBatch:
        if not key:
            raise AnuError("provider_unconfigured", "no api key", sent=False)
        try:
            length = int(length)
        except (TypeError, ValueError):
            raise AnuError("validation_failed", "bad length", sent=False)
        if not (MIN_LENGTH <= length <= MAX_LENGTH):
            raise AnuError("validation_failed",
                           f"length out of range: {length}", sent=False)
        data_type = str(data_type or "")
        if data_type not in DATA_TYPES:
            raise AnuError("validation_failed",
                           f"unknown data type: {data_type[:20]}", sent=False)
        if data_type in HEX_TYPES:
            try:
                size = int(size if size is not None else 1)
            except (TypeError, ValueError):
                raise AnuError("validation_failed", "bad size", sent=False)
            if not (MIN_HEX_SIZE <= size <= MAX_HEX_SIZE):
                raise AnuError("validation_failed",
                               f"size out of range: {size}", sent=False)
        else:
            if size is not None:
                raise AnuError("validation_failed",
                               "size only for hex types", sent=False)
            size = None
        url = validate_endpoint(endpoint)   # origin-guard ДО любого запроса
        now = self._clock()
        if now < self._open_until:
            raise AnuError("provider_unavailable", "circuit_open",
                           retryable=True, sent=False)
        if now < self._next_allowed_at:
            raise AnuError("rate_limit", "backoff", retryable=True, sent=False)
        if (self._last_request_at is not None
                and now - self._last_request_at < self._min_interval):
            raise AnuError("rate_limit", "min_interval", retryable=True,
                           sent=False)
        if self._open_until and not self._probe_used:
            self._probe_used = True      # half-open: ровно один probe
        params: dict[str, Any] = {"length": length, "type": data_type}
        if size is not None:
            params["size"] = size
        headers = {ANU_HEADER: str(key)}     # ключ только в заголовке
        self._last_request_at = now
        try:
            resp = await self._http_get(url, headers, params, self._timeout)
        except asyncio.TimeoutError:
            self._note_failure(now, None)
            raise AnuError("timeout", "request timeout", retryable=True,
                           sent=True)
        except Exception as exc:  # транспорт; ключ в текст не попадает
            name = type(exc).__name__
            is_timeout = "Timeout" in name
            # ConnectTimeout/PoolTimeout — запрос не ушёл (не тратим квоту);
            # Read/WriteTimeout — ушёл (честный unknown через timeout).
            sent = is_timeout and "Connect" not in name and "Pool" not in name
            self._note_failure(now, None)
            raise AnuError("timeout" if is_timeout else "provider_unavailable",
                           f"transport error: {name}",
                           retryable=True, sent=sent)
        status = int(getattr(resp, "status", 0) or 0)
        resp_headers = getattr(resp, "headers", {}) or {}
        text = str(getattr(resp, "text", "") or "")
        if 300 <= status < 400:
            self._note_failure(now, None)
            raise AnuError("redirect_blocked", f"http {status}",
                           sent=True)
        if status in (401, 403):
            self._note_failure(now, None)
            raise AnuError("auth_failed", f"http {status}", sent=True)
        if status == 429:
            retry_after = _parse_retry_after(resp_headers)
            self._note_failure(now, retry_after)
            raise AnuError("quota_exhausted", "http 429", retryable=True,
                           sent=True, retry_after=retry_after)
        if status != 200:
            self._note_failure(now, None)
            code = "provider_unavailable" if status >= 500 else "client_error"
            raise AnuError(code, f"http {status}", retryable=(status >= 500),
                           sent=True)
        try:
            payload = json.loads(text)
        except Exception:
            self._note_failure(now, None)
            raise AnuError("validation_failed", "invalid json", sent=True)
        values = self._validate_payload(payload, length=length,
                                        data_type=data_type, size=size,
                                        key=key)
        self._note_success()
        return AnuBatch(values=values, data_type=data_type, length=length)

    def _validate_payload(self, payload, *, length: int, data_type: str,
                          size: int | None, key: str) -> list:
        def _bad(reason: str):
            self._note_failure(self._clock(), None)
            return AnuError("validation_failed", reason, sent=True)

        if not isinstance(payload, dict):
            raise _bad("schema: not an object")
        if payload.get("success") is not True:
            raise _bad(_clean_error_text(
                payload.get("error") or payload.get("message")
                or "success=false", key))
        ptype = str(payload.get("type") or "")
        if ptype != data_type:
            raise _bad(f"type mismatch: {ptype[:20] or 'missing'}")
        try:
            plen = int(payload.get("length"))
        except (TypeError, ValueError):
            raise _bad("length missing")
        if plen != length:
            raise _bad(f"length mismatch: {plen}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise _bad("data not a list")
        if len(data) != length:
            raise _bad(f"data length: {len(data)}")
        out: list[int] = []
        for item in data:
            if data_type == "uint8" or data_type == "uint16":
                value = self._as_uint(item, UINT_RANGES[data_type] - 1)
                if value is None:
                    raise _bad(f"{data_type} out of range")
                out.append(value)
                continue
            if not isinstance(item, str):
                raise _bad("hex item not a string")
            raw = item.strip().lower()
            expected = int(size or 1) * (2 if data_type == "hex8" else 4)
            if len(raw) != expected or any(
                    c not in "0123456789abcdef" for c in raw):
                raise _bad("hex item invalid")
            out.append(int(raw, 16))
        return out

    @staticmethod
    def _as_uint(item, maximum: int) -> int | None:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            value = item
        elif isinstance(item, str) and item.strip().isdigit():
            value = int(item.strip())
        else:
            return None
        return value if 0 <= value <= maximum else None


# ── LfDR QRNG адаптер (P2; arch D9, `QAN-REC-LFDR-01`) ──────────────────────
# Публичный документированный endpoint без ключа (lfdr.de/QRNG). Используются
# те же механизмы, что у ANU: инъекция `http_get`, origin-guard до запроса,
# circuit breaker/min-interval, существующие коды ошибок и носитель партии
# `AnuBatch` (D9). Ключа нет и поле ключа не создаётся; ANU-клиент этим
# блоком не изменяется.
LFDR_HOST = "lfdr.de"
LFDR_PATH = "/qrng_api/qrng"
LFDR_ENDPOINT = f"https://{LFDR_HOST}{LFDR_PATH}"
LFDR_FORMAT = "HEX"
# Документированный предел сервера — 2147483647 байт; собственный безопасный
# предел равен действующему контракту партии (`MAX_LENGTH` = 1024), чтобы
# запрос/ответ оставались ограниченными. Провайдерский контракт не расширяется
# и не сужается — ограничение объёма действует и для ANU.
LFDR_MIN_LENGTH = MIN_LENGTH
LFDR_MAX_LENGTH = MAX_LENGTH
_LFDR_HEX_CHARS = frozenset("0123456789abcdefABCDEF")


class LfdrError(AnuError):
    """Ошибка LfDR: те же коды/семантика, что `AnuError` (ключа нет).

    Наследование сохраняет существующую обработку (`except AnuError`) и не
    создаёт второй контракт ошибок."""


def validate_lfdr_endpoint(url: str) -> str:
    """Origin-guard LfDR (не SSRF): только https + точный host + ровно
    документированный путь, без userinfo/порта/query/fragment. Иное →
    `scheme_not_allowed`/`invalid_url`; запрос не выполняется."""
    raw = str(url or "").strip()
    if not raw:
        raise LfdrError("invalid_url", "empty endpoint", sent=False)
    try:
        parts = urlsplit(raw)
    except Exception:
        raise LfdrError("invalid_url", "unparsable endpoint", sent=False)
    if parts.scheme.lower() != "https":
        raise LfdrError("scheme_not_allowed",
                        f"scheme={parts.scheme or 'none'}", sent=False)
    if parts.username or parts.password:
        raise LfdrError("invalid_url", "userinfo not allowed", sent=False)
    host = (parts.hostname or "").lower()
    if host != LFDR_HOST:
        raise LfdrError("invalid_url", f"host not allowed: {host}", sent=False)
    try:
        port = parts.port
    except ValueError:
        raise LfdrError("invalid_url", "bad port", sent=False)
    if port not in (None, 443):
        raise LfdrError("invalid_url", "port not allowed", sent=False)
    if (parts.path or "") != LFDR_PATH:
        raise LfdrError("invalid_url", "path not allowed", sent=False)
    if parts.query or parts.fragment:
        raise LfdrError("invalid_url", "query/fragment not allowed", sent=False)
    return LFDR_ENDPOINT


class LfdrClient:
    """Клиент LfDR QRNG (публичный; без ключа и без поля ключа).

    Контракт https://lfdr.de/QRNG: GET `lfdr.de/qrng_api/qrng` с
    `length` (1..1024) и `format=HEX`; ответ `{"length": N, "qrn": "<2N hex>"}`.
    Один байт = пара hex-символов → uint8. Таймаут; 3xx → `redirect_blocked`
    (redirect не выполняется); 429 → `rate_limit` (+Retry-After); 4xx →
    `client_error`; 5xx → `provider_unavailable`; битый JSON/схема/длина/hex →
    `validation_failed`. Circuit breaker/min-interval — та же семантика, что в
    `AnuClient` (3 fails → open 60 c → half-open один probe), но состояние
    отдельное: падение LfDR не открывает ANU-цепь. Значения партии — uint8.
    """

    def __init__(self, *, http_get: Callable | None = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 min_interval: float = 1.0, circuit_fails: int = 3,
                 circuit_cooldown: float = 60.0, clock: Callable | None = None
                 ) -> None:
        self._http_get = http_get or _default_http_get
        self._timeout = float(timeout)
        self._min_interval = float(min_interval)
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = float(circuit_cooldown)
        self._clock = clock or time.monotonic
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._last_request_at: float | None = None
        self._next_allowed_at = 0.0

    # ── конфигурация (hot-значения передаёт владелец клиента) ──────────────
    def configure(self, *, timeout: float, min_interval: float,
                  circuit_fails: int, circuit_cooldown: float) -> None:
        self._timeout = float(timeout)
        self._min_interval = max(0.0, float(min_interval))
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = max(1.0, float(circuit_cooldown))

    def status(self) -> dict:
        return {
            "fails": int(self._fails),
            "circuit_open_until": float(self._open_until),
            "next_allowed_at": float(self._next_allowed_at),
            "last_request_at": self._last_request_at,
        }

    def available(self) -> bool:
        now = self._clock()
        return now >= self._open_until and now >= self._next_allowed_at

    # ── breaker/backoff (паритет с AnuClient; состояние независимое) ───────
    def _note_failure(self, now: float, retry_after: int | None) -> None:
        self._fails += 1
        backoff = min(self._cooldown, float(2 ** min(self._fails, 6)))
        if retry_after:
            backoff = max(backoff, float(retry_after))
        self._next_allowed_at = now + backoff
        if self._fails >= self._circuit_fails:
            self._open_until = now + self._cooldown
            self._probe_used = False

    def _note_success(self) -> None:
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._next_allowed_at = 0.0

    # ── fetch ──────────────────────────────────────────────────────────────
    async def fetch(self, *, length: int = DEFAULT_BATCH_LENGTH,
                    endpoint: str = LFDR_ENDPOINT) -> AnuBatch:
        if isinstance(length, bool) or not isinstance(length, (int, str)):
            raise LfdrError("validation_failed", "bad length", sent=False)
        try:
            length = int(length)
        except (TypeError, ValueError):
            raise LfdrError("validation_failed", "bad length", sent=False)
        if not (LFDR_MIN_LENGTH <= length <= LFDR_MAX_LENGTH):
            raise LfdrError("validation_failed",
                            f"length out of range: {length}", sent=False)
        url = validate_lfdr_endpoint(endpoint)   # origin-guard ДО запроса
        now = self._clock()
        if now < self._open_until:
            raise LfdrError("provider_unavailable", "circuit_open",
                            retryable=True, sent=False)
        if now < self._next_allowed_at:
            raise LfdrError("rate_limit", "backoff", retryable=True,
                            sent=False)
        if (self._last_request_at is not None
                and now - self._last_request_at < self._min_interval):
            raise LfdrError("rate_limit", "min_interval", retryable=True,
                            sent=False)
        if self._open_until and not self._probe_used:
            self._probe_used = True      # half-open: ровно один probe
        params: dict[str, Any] = {"length": length, "format": LFDR_FORMAT}
        headers: dict[str, str] = {}     # ключа нет: заголовков авторизации нет
        self._last_request_at = now
        started = time.monotonic()
        try:
            resp = await self._http_get(url, headers, params, self._timeout)
        except asyncio.TimeoutError:
            self._note_failure(now, None)
            raise LfdrError("timeout", "request timeout", retryable=True,
                            sent=True)
        except Exception as exc:  # транспорт; тела ответа ещё нет
            name = type(exc).__name__
            is_timeout = "Timeout" in name
            # ConnectTimeout/PoolTimeout — запрос не ушёл; Read/Write — ушёл.
            sent = is_timeout and "Connect" not in name and "Pool" not in name
            self._note_failure(now, None)
            raise LfdrError("timeout" if is_timeout else "provider_unavailable",
                            f"transport error: {name}",
                            retryable=True, sent=sent)
        status = int(getattr(resp, "status", 0) or 0)
        resp_headers = getattr(resp, "headers", {}) or {}
        text = str(getattr(resp, "text", "") or "")
        if 300 <= status < 400:
            self._note_failure(now, None)
            raise LfdrError("redirect_blocked", f"http {status}", sent=True)
        if status in (401, 403):
            self._note_failure(now, None)
            raise LfdrError("auth_failed", f"http {status}", sent=True)
        if status == 429:
            retry_after = _parse_retry_after(resp_headers)
            self._note_failure(now, retry_after)
            raise LfdrError("rate_limit", "http 429", retryable=True,
                            sent=True, retry_after=retry_after)
        if status != 200:
            # Тело ошибки провайдер отдаёт как `{"error": "..."}`; текст
            # очищается и обрезается, значения партии не появляются.
            self._note_failure(now, None)
            code = "provider_unavailable" if status >= 500 else "client_error"
            raise LfdrError(code, self._error_reason(text, status),
                            retryable=(status >= 500), sent=True)
        try:
            payload = json.loads(text)
        except Exception:
            self._note_failure(now, None)
            raise LfdrError("validation_failed", "invalid json", sent=True)
        values = self._validate_payload(payload, length=length)
        self._note_success()
        return AnuBatch(
            values=values, data_type="uint8", length=length,
            provider=PROVIDER_ID_LFDR,
            latency_ms=int((time.monotonic() - started) * 1000))

    @staticmethod
    def _error_reason(text: str, status: int) -> str:
        try:
            payload = json.loads(text)
        except Exception:
            return f"http {status}"
        if isinstance(payload, dict) and payload.get("error") is not None:
            return _clean_error_text(payload.get("error"))
        return f"http {status}"

    def _validate_payload(self, payload, *, length: int) -> list[int]:
        def _bad(reason: str):
            self._note_failure(self._clock(), None)
            return LfdrError("validation_failed", reason, sent=True)

        if not isinstance(payload, dict):
            raise _bad("schema: not an object")
        if payload.get("error") is not None:
            raise _bad(_clean_error_text(payload.get("error")))
        declared = payload.get("length")
        if isinstance(declared, bool) or not isinstance(declared, (int, str)):
            raise _bad("length missing")
        text = str(declared).strip()
        if not (text.isascii() and text.isdigit()):
            raise _bad("length missing")
        # Длина ответа — короткое десятичное число (≤4 цифр по контракту,
        # запас до 12). Строку длиннее заведомо вне диапазона отвергаем, не
        # вызывая int(): CPython бросает ValueError на >4300 цифрах
        # (int-max-str-digits), и он вылетал бы из fetch()/check() мимо
        # контракта AnuError/LfdrError, не отмечая failure у breaker'а (F1).
        if len(text) > 12:
            raise _bad("length out of range")
        try:
            declared_length = int(text)
        except ValueError:      # pragma: no cover - защитная ветка
            raise _bad("length out of range")
        if declared_length != length:
            raise _bad(f"length mismatch: {text[:12]}")
        qrn = payload.get("qrn")
        if not isinstance(qrn, str):
            raise _bad("qrn not a string")
        if len(qrn) != length * 2:
            raise _bad(f"qrn length: {len(qrn)}")
        if any(c not in _LFDR_HEX_CHARS for c in qrn):
            raise _bad("qrn invalid hex")
        return [int(qrn[i:i + 2], 16) for i in range(0, len(qrn), 2)]

    async def check(self, *, length: int = LFDR_MIN_LENGTH) -> dict:
        """Одна малая живая проверка (без ключа): формат/длина/латентность.

        Возвращает только метаданные — сырые значения наружу не отдаются."""
        try:
            batch = await self.fetch(length=length)
        except AnuError as exc:
            return {"provider": PROVIDER_ID_LFDR, "healthy": False,
                    "blocker": exc.code, "reason": exc.reason,
                    "requires_key": False, "checked_at": int(time.time())}
        return {"provider": PROVIDER_ID_LFDR, "healthy": True, "blocker": None,
                "length": batch.length, "latency_ms": batch.latency_ms,
                "requires_key": False, "checked_at": int(time.time())}


async def lfdr_fetch(*, length: int = DEFAULT_BATCH_LENGTH,
                     client: LfdrClient | None = None,
                     http_get: Callable | None = None,
                     timeout: float = DEFAULT_TIMEOUT_SECONDS) -> AnuBatch:
    """Реестровая точка входа LfDR (arch D1): один батч через адаптер.

    `client` — общий клиент владельца (breaker/min-interval сохраняются между
    вызовами). Без него создаётся одноразовый клиент без min-interval
    (проверка/тесты); состояние breaker между такими вызовами не переносится."""
    adapter = client if client is not None else LfdrClient(
        http_get=http_get, timeout=timeout, min_interval=0.0)
    return await adapter.fetch(length=length)


async def lfdr_check(*, client: LfdrClient | None = None,
                     http_get: Callable | None = None,
                     timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Реестровая точка входа проверки LfDR (малая выборка, без ключа)."""
    adapter = client if client is not None else LfdrClient(
        http_get=http_get, timeout=timeout, min_interval=0.0)
    return await adapter.check()


# P2: адаптер подключён к реестру (D9).
PROVIDERS[PROVIDER_ID_LFDR] = replace(
    PROVIDERS[PROVIDER_ID_LFDR], fetch=lfdr_fetch, check=lfdr_check)


# ── IBM Quantum Platform адаптер (P5; QAN-REC-IBM-01…03) ───────────────────
# Один адаптер внутри существующего контура: реальный QPU Sampler поверх
# `qiskit-ibm-runtime`, раздельные read-only проверка доступа и ограниченный
# hardware smoke, durable job lifecycle в существующих `task_jobs`. Симулятор,
# `quasi_dists`, фиксированные counts и локальный PRNG в тракте отвергаются.
class IbmError(AnuError):
    """Ошибка IBM с явной стадией (key/crn/instance/region/...).

    Наследование сохраняет существующую обработку `except AnuError`; второй
    контракт ошибок не создаётся. `stage` называет фактическую стадию отказа,
    `job_state` — распознанное состояние IBM job (durable cursor)."""

    def __init__(self, code: str, reason: str = "", *, stage: str = "",
                 job_state: str | None = None, retryable: bool = False,
                 sent: bool = False, retry_after: int | None = None) -> None:
        self.stage = str(stage or "")[:48]
        self.job_state = job_state
        super().__init__(code, reason, retryable=retryable, sent=sent,
                         retry_after=retry_after)


def _qiskit_runtime_available() -> bool:
    """Есть ли установленный `qiskit-ibm-runtime` (импорт lazy).

    Проверка `find_spec` не импортирует тяжёлый пакет на горячем пути; сам
    импорт выполняется только при реальном запросе/проверке IBM."""
    try:
        return importlib.util.find_spec("qiskit_ibm_runtime") is not None
    except Exception:       # pragma: no cover - защитная ветка
        return False


def _default_qiskit_service(*, api_key: str, crn: str, instance: str,
                            region: str, channel: str):
    """Создать официальный `QiskitRuntimeService` (IBM Cloud)."""
    from qiskit_ibm_runtime import QiskitRuntimeService
    return QiskitRuntimeService(
        channel=channel, token=api_key, instance=(crn or instance),
        region=region)


def _default_qiskit_sampler(*, backend):
    """Официальный QPU Sampler (не Aer/симулятор)."""
    from qiskit_ibm_runtime import SamplerV2
    try:
        sampler = SamplerV2(mode=backend)
    except TypeError:       # совместимость сигнатуры ранних 0.4x
        sampler = SamplerV2(backend=backend)
    try:
        # Явный старт из |0>: H на каждом кубите даёт равномерные биты.
        sampler.options.execution.init_qubits = True
    except Exception:
        pass
    return sampler


def _default_ibm_circuit(num_qubits: int):
    """Схема измерения: равномерная суперпозиция + measure_all (`meas`)."""
    from qiskit import QuantumCircuit
    circuit = QuantumCircuit(num_qubits)
    circuit.h(range(num_qubits))
    circuit.measure_all()
    return circuit


def _default_ibm_transpiler(circuit, backend):
    """Привести схему к ISA целевого IBM backend (обязательно для Sampler)."""
    from qiskit.transpiler.preset_passmanagers import (
        generate_preset_pass_manager)
    pm = generate_preset_pass_manager(
        target=backend.target, optimization_level=1)
    return pm.run(circuit)


def _ibm_attr(obj, name: str, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:       # pragma: no cover - защитная ветка
        return default


def _ibm_backend_simulator(backend) -> bool | None:
    """True/False/None — симулятор ли backend (None = не подтверждено)."""
    if backend is None:
        return None
    value = _ibm_attr(backend, "simulator", None)
    if value is None:
        cfg = _ibm_attr(backend, "configuration", None)
        if callable(cfg):
            try:
                cfg = cfg()
            except Exception:
                cfg = None
        value = _ibm_attr(cfg, "simulator", None)
    if isinstance(value, bool):
        return value
    return None


def _ibm_backend_name(backend) -> str:
    if isinstance(backend, str):
        return backend.strip()[:120]
    value = _ibm_attr(backend, "name", None)
    if callable(value):
        try:
            value = value()
        except Exception:
            value = None
    return str(value or "").strip()[:120]


def _ibm_backend_qubits(backend) -> int:
    value = _ibm_attr(backend, "num_qubits", None)
    if value is None:
        cfg = _ibm_attr(backend, "configuration", None)
        if callable(cfg):
            try:
                cfg = cfg()
            except Exception:
                cfg = None
        value = _ibm_attr(cfg, "num_qubits", 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ibm_backend_status(backend):
    status = _ibm_attr(backend, "status", None)
    if callable(status):
        try:
            return status()
        except Exception:
            return None
    return status


def _ibm_backend_pending(backend) -> int:
    status = _ibm_backend_status(backend)
    try:
        return max(0, int(_ibm_attr(status, "pending_jobs", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _ibm_backend_operational(backend) -> bool:
    status = _ibm_backend_status(backend)
    if status is None:
        return True
    return bool(_ibm_attr(status, "operational", True)) is not False


def _ibm_backend_eligible(backend) -> bool:
    """Реальный аппаратный backend, пригодный для 16-битных значений."""
    return (_ibm_backend_simulator(backend) is False
            and _ibm_backend_operational(backend)
            and _ibm_backend_qubits(backend) >= IBM_MIN_QUBITS)


def _ibm_backend_public(backend) -> dict:
    return {
        "name": _ibm_backend_name(backend),
        "num_qubits": _ibm_backend_qubits(backend),
        "pending_jobs": _ibm_backend_pending(backend),
        "operational": _ibm_backend_operational(backend),
        "simulator": _ibm_backend_simulator(backend) is True,
    }


def _ibm_error_code(exc: BaseException,
                    default: str = "provider_unavailable") -> str:
    """Свести официальную ошибку IBM/qiskit к действующим reason-кодам."""
    if isinstance(exc, AnuError):
        return str(exc.code)
    status = None
    for attr in ("status_code", "status", "http_status", "code"):
        raw = _ibm_attr(exc, attr, None)
        if isinstance(raw, int):
            status = raw
            break
        if isinstance(raw, str) and raw.strip().isdigit():
            status = int(raw.strip())
            break
    if status in (401,):
        return "auth_failed"
    if status in (403,):
        return "permission_denied"
    if status == 404:
        return "invalid_instance"
    if status == 429:
        return "rate_limit"
    text = f"{type(exc).__name__} {exc}".lower()
    if "quota" in text or "usage limit" in text or "limit reached" in text:
        return "quota_exhausted"
    if "permission" in text or "forbidden" in text or "not authorized" in text:
        return "permission_denied"
    if "unauthor" in text or "auth" in text:
        return "auth_failed"
    if "instance" in text or "crn" in text:
        return "invalid_instance"
    if "region" in text:
        return "region_not_available"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return default


def _ibm_stage_for_code(code: str) -> str:
    return {
        "provider_unconfigured": "key",
        "dependency_missing": "dependency",
        "invalid_channel": "channel",
        "invalid_instance": "instance",
        "invalid_region": "region",
        "region_not_available": "region",
        "permission_denied": "permission",
        "auth_failed": "permission",
        "no_backend": "no_backend",
        "quota_exhausted": "permission",
    }.get(str(code), "request")


def _ibm_crn_region(crn) -> str:
    """Регион из CRN (`crn:v1:bluemix:public:quantum-compute:<region>:...`)."""
    parts = str(crn or "").split(":")
    if len(parts) > 5 and parts[0].lower() == "crn":
        region = parts[5].strip()
        if region and len(region) <= 32:
            return region
    return ""


def _ibm_instance_region(instances, instance_ref: str) -> str:
    """Фактический регион instance из ответа IBM (CRN/список instances)."""
    direct = _ibm_crn_region(instance_ref)
    if direct:
        return direct
    for item in instances or ():
        crn = _ibm_attr(item, "crn", None)
        name = _ibm_attr(item, "name", None)
        if isinstance(item, dict):
            crn = item.get("crn", crn)
            name = item.get("name", name)
        if instance_ref and instance_ref not in (str(crn or ""),
                                                 str(name or "")):
            continue
        region = _ibm_crn_region(crn)
        if region:
            return region
    return ""


def _ibm_plan_from_instances(instances, instance_ref: str) -> str | None:
    """Фактический plan из ответа IBM, если он там есть; иначе None."""
    for item in instances or ():
        crn = _ibm_attr(item, "crn", None)
        name = _ibm_attr(item, "name", None)
        if isinstance(item, dict):
            crn = item.get("crn", crn)
            name = item.get("name", name)
        if instance_ref and instance_ref not in (str(crn or ""), str(name or "")):
            continue
        plan = _ibm_attr(item, "plan", None)
        if isinstance(item, dict):
            plan = item.get("plan", plan)
        if plan:
            return str(plan).strip()[:40]
    return None


# Реальные поля `QiskitRuntimeService.usage()` 0.52.1 (секунды и RU) +
# обратная совместимость с прежними краткими именами.
_IBM_USAGE_FIELDS = (
    "usage_limit_seconds", "usage_consumed_seconds",
    "usage_remaining_seconds", "usage_limit_ru", "usage_consumed_ru",
    "usage_remaining_ru", "usage_limit_reached", "period", "plan",
    "usage", "used", "used_seconds", "limit", "limit_seconds",
    "remaining", "remaining_seconds",
)


def _ibm_usage_public(service) -> dict | None:
    """Публичная часть usage без провайдерских секретов (read-only)."""
    usage = _ibm_attr(service, "usage", None)
    if callable(usage):
        try:
            usage = usage()
        except Exception:
            return None
    if usage is None:
        return None
    data: dict = {}
    if isinstance(usage, dict):
        data = usage
    else:
        to_dict = _ibm_attr(usage, "to_dict", None)
        if callable(to_dict):
            try:
                data = to_dict() or {}
            except Exception:
                data = {}
        if not data:
            for name in _IBM_USAGE_FIELDS:
                value = _ibm_attr(usage, name, None)
                if value is not None:
                    data[name] = value
    out = {}
    for key in _IBM_USAGE_FIELDS:
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float, str)):
            out[key] = value
    return out or None


def _ibm_normalize_status(status) -> str | None:
    """Нормализовать состояние IBM job; None — состояние недоступно."""
    text = str(getattr(status, "name", status) or "").strip().lower()
    if not text:
        return None
    if "done" in text or "complete" in text:
        return IBM_JOB_COMPLETED
    if "error" in text or "fail" in text:
        return IBM_JOB_FAILED
    if "cancel" in text:
        return IBM_JOB_CANCELLED
    if "queue" in text or "pending" in text or "initial" in text \
            or "validat" in text:
        return IBM_JOB_QUEUED
    if "run" in text or "execut" in text:
        return IBM_JOB_RUNNING
    return IBM_JOB_RUNNING


def _ibm_debias_bitstrings(bitstrings) -> tuple[list[int], dict]:
    """Детерминированный von Neumann debias сырых measurement bits.

    Каждая пара битов `01` → 0, `10` → 1, `00`/`11` отбрасывается. Для
    независимых битов с ЛЮБОЙ постоянной вероятностью единицы результат
    несмещён; физическое смещение явно измеряется и попадает в provenance.
    """
    bits: list[int] = []
    raw_ones = 0
    raw_total = 0
    pairs = 0
    accepted = 0
    # Пары — соседние shots на ОДНОЙ позиции кубита: не смешиваем разные
    # кубиты с разным readout-смещением и не ловим crosstalk внутри shot.
    for index in range(0, len(bitstrings) - 1, 2):
        first, second = bitstrings[index], bitstrings[index + 1]
        raw_total += len(first) + len(second)
        raw_ones += first.count("1") + second.count("1")
        for pos in range(min(len(first), len(second))):
            pairs += 1
            left, right = first[pos], second[pos]
            if left != right:
                bits.append(1 if left == "1" else 0)
                accepted += 1
    stats = {
        "raw_bits": raw_total,
        "raw_ones": raw_ones,
        "bias": (round(raw_ones / raw_total, 6) if raw_total else None),
        "pairs": pairs,
        "accepted_pairs": accepted,
        "discarded_pairs": pairs - accepted,
        "unbiased_bits": len(bits),
    }
    return bits, stats


def _ibm_pack_values(bits: list[int], limit: int) -> list[int]:
    """Упаковать unbiased-биты в uint16 (big-endian, детерминированно)."""
    values: list[int] = []
    upper = len(bits) - 15
    for index in range(0, max(0, upper), 16):
        value = 0
        for bit in bits[index:index + 16]:
            value = (value << 1) | int(bit)
        values.append(value)
    if limit > 0:
        return values[:limit]
    return values


def _ibm_shots_for(length: int, num_qubits: int) -> int:
    """Bounded batch shots: ожидаемый debias-yield ≈ 1/4 сырых битов."""
    needed_bits = max(16, int(length) * 16)
    qubits = max(1, int(num_qubits))
    shots = (needed_bits * 5 + qubits - 1) // qubits
    shots = max(IBM_MIN_SHOTS, min(IBM_MAX_SHOTS, shots))
    return ((shots + 63) // 64) * 64


def _ibm_error_result(*, code: str, stage: str, reason: str = "",
                      job_state: str | None = None,
                      key_present: bool = False,
                      crn_present: bool = False,
                      instance: str = "", region: str = "",
                      channel: str = "", plan: str | None = None,
                      usage: dict | None = None,
                      backends: list | None = None,
                      selected_backend: str | None = None,
                      checked_at: int | None = None) -> dict:
    return {
        "provider": PROVIDER_ID_IBM, "healthy": False, "blocker": str(code),
        "stage": str(stage), "reason": str(reason or "")[:160],
        "job_state": job_state,
        "key_present": bool(key_present), "crn_present": bool(crn_present),
        "instance": str(instance or "")[:120],
        "region": str(region or "")[:40],
        "channel": str(channel or "")[:48],
        "plan": plan, "usage": usage,
        "backends": list(backends or []),
        "selected_backend": selected_backend,
        "is_simulator": False,
        "checked_at": int(checked_at if checked_at is not None
                          else time.time()),
    }


class IbmQuantumRuntimeClient:
    """IBM Quantum Platform adapter: реальный QPU Sampler + durable job.

    Разделение действий:
      * `check_access` — строго read-only: key/CRN/instance/region/backends/
        queue/usage; Sampler не создаётся, job не отправляется;
      * `hardware_smoke` — отдельное ограниченное измерение на реальном QPU;
      * `fetch` — партия настоящих measurement bits для рабочего запаса.

    `service_factory`/`sampler_factory`/`circuit_factory` инъектируются в
    тестах; по умолчанию используются официальные qiskit-объекты. Никаких
    имитаций измерения в рабочем тракте: simulator/quasi_dists отвергаются.
    """

    def __init__(self, *, service_factory: Callable | None = None,
                 sampler_factory: Callable | None = None,
                 circuit_factory: Callable | None = None,
                 transpiler: Callable | None = None,
                 timeout: float = DEFAULT_IBM_HTTP_TIMEOUT_SECONDS,
                 poll_interval: float = DEFAULT_IBM_POLL_INTERVAL_SECONDS,
                 job_max_age: float = DEFAULT_IBM_JOB_MAX_AGE_SECONDS,
                 circuit_fails: int = 3, circuit_cooldown: float = 60.0,
                 clock: Callable | None = None,
                 sleeper: Callable | None = None) -> None:
        self._service_factory = service_factory or _default_qiskit_service
        self._sampler_factory = sampler_factory or _default_qiskit_sampler
        self._circuit_factory = circuit_factory or _default_ibm_circuit
        self._transpiler = transpiler or _default_ibm_transpiler
        self._timeout = float(timeout)
        self._poll_interval = max(0.0, float(poll_interval))
        self._job_max_age = max(1.0, float(job_max_age))
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = max(1.0, float(circuit_cooldown))
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._last_error: str | None = None
        self._last_success_at: int | None = None
        self._last_failure_at: int | None = None

    # ── состояние/breaker (паритет с существующими клиентами) ─────────────
    def configure(self, *, timeout: float, poll_interval: float,
                  job_max_age: float, circuit_fails: int,
                  circuit_cooldown: float) -> None:
        self._timeout = float(timeout)
        self._poll_interval = max(0.0, float(poll_interval))
        self._job_max_age = max(1.0, float(job_max_age))
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = max(1.0, float(circuit_cooldown))

    def status(self) -> dict:
        return {
            "fails": int(self._fails),
            "circuit_open_until": float(self._open_until),
            "last_error": self._last_error,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
        }

    def available(self) -> bool:
        return self._clock() >= self._open_until

    def _note_failure(self, now: float, code: str) -> None:
        self._fails += 1
        self._last_error = str(code)[:80]
        self._last_failure_at = int(time.time())
        backoff = min(self._cooldown, float(2 ** min(self._fails, 6)))
        if self._fails >= self._circuit_fails:
            self._open_until = now + self._cooldown
            self._probe_used = False

    def _note_success(self) -> None:
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._last_error = None
        self._last_success_at = int(time.time())

    def _assert_available(self, now: float) -> None:
        if now < self._open_until:
            raise IbmError("provider_unavailable", "circuit_open",
                           retryable=True, sent=False, stage="circuit")

    async def _call(self, fn, *args, **kwargs):
        """Выполнить блокирующий qiskit-вызов вне event loop с таймаутом.

        Сетевые/вычислительные операции SDK не должны задерживать Telegram:
        они уходят в поток, а `http_timeout` ограничивает ожидание."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs),
                timeout=self._timeout)
        except asyncio.TimeoutError:
            raise IbmError("timeout", "ibm request timeout", stage="request",
                           retryable=True, sent=True)

    async def _job_state(self, job) -> str | None:
        status = _ibm_attr(job, "status", None)
        if not callable(status):
            return _ibm_normalize_status(status)
        try:
            return _ibm_normalize_status(await self._call(status))
        except Exception:
            return None

    async def _job_usage(self, job) -> tuple[float | None, str]:
        """Фактический QPU usage по данным IBM (вне event loop)."""
        usage = _ibm_attr(job, "usage", None)
        if callable(usage):
            try:
                usage = await self._call(usage)
            except Exception:
                usage = None
        try:
            if usage is not None and not isinstance(usage, bool):
                value = float(usage)
                if value >= 0:
                    return value, "job.usage"
        except (TypeError, ValueError):
            pass
        metrics = _ibm_attr(job, "metrics", None)
        if callable(metrics):
            try:
                metrics = await self._call(metrics)
            except Exception:
                metrics = None
        if isinstance(metrics, dict):
            for key in ("usage", "usage_seconds", "qpu_time", "qpu_seconds"):
                raw = metrics.get(key)
                try:
                    if raw is not None and not isinstance(raw, bool) \
                            and not isinstance(raw, dict):
                        value = float(raw)
                        if value >= 0:
                            return value, f"job.metrics.{key}"
                except (TypeError, ValueError):
                    continue
            usage_data = metrics.get("usage")
            if isinstance(usage_data, dict):
                for key in ("qpu_charge_time_seconds", "value",
                            "usage_seconds", "qpu_time"):
                    raw = usage_data.get(key)
                    try:
                        if raw is not None and not isinstance(raw, bool):
                            value = float(raw)
                            if value >= 0:
                                return value, f"job.metrics.usage.{key}"
                    except (TypeError, ValueError):
                        continue
        return None, "unavailable"

    # ── валидация подключения (без сети) ───────────────────────────────────
    def _validated(self, api_key, crn, instance, region,
                   channel) -> tuple[str, str, str, str, str]:
        key = str(api_key or "").strip()
        if not key:
            raise IbmError("provider_unconfigured", "no api key",
                           stage="key", sent=False)
        # Инъекция фабрики в тестах — доказательство, что зависимость не
        # требуется для контрактных проверок; в продакшене обязателен
        # установленный официальный пакет.
        if (self._service_factory is _default_qiskit_service
                and not _qiskit_runtime_available()):
            raise IbmError("dependency_missing",
                           "qiskit-ibm-runtime not installed",
                           stage="dependency", sent=False)
        channel_text = str(channel or IBM_CHANNEL).strip()
        if channel_text != IBM_CHANNEL:
            raise IbmError("invalid_channel",
                           f"channel not allowed: {channel_text[:32]}",
                           stage="channel", sent=False)
        region_text = str(region or IBM_REGION_DEFAULT).strip()
        if (not region_text or len(region_text) > 32
                or any(not (ch.isalnum() or ch in "-_")
                       for ch in region_text)):
            raise IbmError("invalid_region",
                           f"invalid region: {region_text[:32]}",
                           stage="region", sent=False)
        instance_text = str(instance or IBM_INSTANCE_DEFAULT).strip()
        crn_text = str(crn or "").strip()
        if not instance_text and not crn_text:
            raise IbmError("provider_unconfigured",
                           "instance/CRN missing", stage="instance",
                           sent=False)
        return key, crn_text, instance_text, region_text, channel_text

    async def _service(self, *, api_key: str, crn: str, instance: str,
                       region: str, channel: str):
        try:
            return await self._call(
                self._service_factory, api_key=api_key, crn=crn,
                instance=instance, region=region, channel=channel)
        except IbmError:
            raise
        except Exception as exc:
            code = _ibm_error_code(exc, "auth_failed")
            raise IbmError(code, _clean_error_text(str(exc), api_key),
                           stage=_ibm_stage_for_code(code), sent=False)

    async def _instances(self, service) -> list:
        getter = _ibm_attr(service, "instances", None)
        if not callable(getter):
            return []
        try:
            return list(await self._call(getter) or [])
        except Exception:
            return []

    async def _backends(self, service, instance_ref: str) -> list:
        getter = _ibm_attr(service, "backends", None)
        if not callable(getter):
            return []
        try:
            return list(await self._call(getter,
                                         instance=instance_ref) or [])
        except TypeError:
            return list(await self._call(getter) or [])

    async def _backend_infos(self, backends) -> list[tuple[object, dict]]:
        """Снимок backend'ов (status/config) — целиком вне event loop."""
        infos: list[tuple[object, dict]] = []
        for backend in backends:
            try:
                info = await self._call(_ibm_backend_public, backend)
            except Exception:
                continue
            infos.append((backend, info))
        return infos

    @staticmethod
    def _pick_from_infos(infos):
        eligible = [
            (backend, info) for backend, info in infos
            if info.get("simulator") is False
            and info.get("operational") is True
            and int(info.get("num_qubits") or 0) >= IBM_MIN_QUBITS]
        if not eligible:
            return None
        eligible.sort(key=lambda item: (
            int(item[1].get("pending_jobs") or 0),
            str(item[1].get("name") or "")))
        return eligible[0]

    @staticmethod
    def _check_success(*, instance: str, region: str, channel: str,
                       plan: str | None, usage: dict | None,
                       backends: list, backend_info: dict,
                       checked_at: int) -> dict:
        return {
            "provider": PROVIDER_ID_IBM, "healthy": True, "blocker": None,
            "stage": None, "reason": "",
            "key_present": True, "crn_present": False,
            "instance": instance[:120], "region": region[:40],
            "channel": channel[:48], "plan": plan, "usage": usage,
            "backends": backends,
            "selected_backend": backend_info.get("name"),
            "queue": ({"pending_jobs": backend_info.get("pending_jobs")}
                      if backend_info else None),
            "queues": {b.get("name"): b.get("pending_jobs")
                       for b in backends
                       if b.get("name") and b.get("simulator") is False},
            "is_simulator": False, "checked_at": int(checked_at),
        }

    async def check_access(self, *, api_key: str, crn: str = "",
                           instance: str = IBM_INSTANCE_DEFAULT,
                           region: str = IBM_REGION_DEFAULT,
                           channel: str = IBM_CHANNEL) -> dict:
        """Read-only проверка: без Sampler и без единого job."""
        checked_at = int(time.time())
        crn_present = bool(str(crn or "").strip())
        try:
            key, crn_text, instance_text, region_text, channel_text = \
                self._validated(api_key, crn, instance, region, channel)
        except IbmError as exc:
            return _ibm_error_result(
                code=exc.code, stage=exc.stage, reason=exc.reason,
                key_present=bool(str(api_key or "").strip()),
                crn_present=crn_present, instance=str(instance or ""),
                region=str(region or ""), channel=str(channel or ""),
                checked_at=checked_at)
        now = self._clock()
        try:
            self._assert_available(now)
        except IbmError as exc:
            return _ibm_error_result(
                code=exc.code, stage=exc.stage, reason=exc.reason,
                key_present=True, crn_present=crn_present,
                instance=instance_text, region=region_text,
                channel=channel_text, checked_at=checked_at)
        try:
            service = await self._service(
                api_key=key, crn=crn_text, instance=instance_text,
                region=region_text, channel=channel_text)
            instance_ref = crn_text or instance_text
            instances = await self._instances(service)
            if instances:
                known = set()
                for item in instances:
                    known.add(str(_ibm_attr(item, "crn", "") or ""))
                    known.add(str(_ibm_attr(item, "name", "") or ""))
                    if isinstance(item, dict):
                        known.add(str(item.get("crn") or ""))
                        known.add(str(item.get("name") or ""))
                if instance_ref not in known:
                    self._note_failure(now, "invalid_instance")
                    return _ibm_error_result(
                        code="invalid_instance", stage="instance",
                        reason="instance/CRN not found in IBM response",
                        key_present=True, crn_present=crn_present,
                        instance=instance_text, region=region_text,
                        channel=channel_text, checked_at=checked_at)
            actual_region = _ibm_instance_region(instances, instance_ref)
            if (actual_region
                    and actual_region.lower() != region_text.lower()):
                self._note_failure(now, "invalid_region")
                return _ibm_error_result(
                    code="invalid_region", stage="region",
                    reason=(f"instance region={actual_region[:24]} "
                            f"!= configured={region_text[:24]}"),
                    key_present=True, crn_present=crn_present,
                    instance=instance_text, region=region_text,
                    channel=channel_text, checked_at=checked_at)
            backends_raw = await self._backends(service, instance_ref)
            infos = await self._backend_infos(backends_raw)
            public = [info for _backend, info in infos]
            picked = self._pick_from_infos(infos)
            plan = _ibm_plan_from_instances(instances, instance_ref)
            try:
                usage = await self._call(_ibm_usage_public, service)
            except IbmError:
                usage = None
            if picked is None:
                self._note_failure(now, "no_backend")
                return _ibm_error_result(
                    code="no_backend", stage="no_backend",
                    reason="no operational hardware QPU",
                    key_present=True, crn_present=crn_present,
                    instance=instance_text, region=region_text,
                    channel=channel_text, plan=plan, usage=usage,
                    backends=public, checked_at=checked_at)
            self._note_success()
            success = self._check_success(
                instance=instance_text, region=region_text,
                channel=channel_text, plan=plan, usage=usage,
                backends=public, backend_info=picked[1],
                checked_at=checked_at)
            success["crn_present"] = crn_present
            return success
        except IbmError as exc:
            self._note_failure(now, exc.code)
            return _ibm_error_result(
                code=exc.code, stage=exc.stage, reason=exc.reason,
                key_present=True, crn_present=crn_present,
                instance=instance_text, region=region_text,
                channel=channel_text, checked_at=checked_at)
        except Exception as exc:
            code = _ibm_error_code(exc)
            self._note_failure(now, code)
            return _ibm_error_result(
                code=code, stage=_ibm_stage_for_code(code),
                reason=_clean_error_text(str(exc), key),
                key_present=True, crn_present=crn_present,
                instance=instance_text, region=region_text,
                channel=channel_text, checked_at=checked_at)

    async def hardware_smoke(self, *, api_key: str, crn: str = "",
                             instance: str = IBM_INSTANCE_DEFAULT,
                             region: str = IBM_REGION_DEFAULT,
                             channel: str = IBM_CHANNEL,
                             shots: int = IBM_SMOKE_SHOTS,
                             job_store=None, supervisor=None,
                             account_key: str = "",
                             config_fp: str = "") -> dict:
        """Отдельное ограниченное измерение на реальном QPU (не зачисляется)."""
        checked_at = int(time.time())
        crn_present = bool(str(crn or "").strip())
        try:
            key, crn_text, instance_text, region_text, channel_text = \
                self._validated(api_key, crn, instance, region, channel)
            shots = max(64, min(4096, int(shots)))
        except IbmError as exc:
            return _ibm_error_result(
                code=exc.code, stage=exc.stage, reason=exc.reason,
                key_present=bool(str(api_key or "").strip()),
                crn_present=crn_present, instance=str(instance or ""),
                region=str(region or ""), channel=str(channel or ""),
                checked_at=checked_at)
        except (TypeError, ValueError):
            return _ibm_error_result(
                code="validation_failed", stage="shots",
                reason="invalid shots", key_present=bool(api_key),
                crn_present=crn_present, checked_at=checked_at)
        now = self._clock()
        try:
            self._assert_available(now)
            service = await self._service(
                api_key=key, crn=crn_text, instance=instance_text,
                region=region_text, channel=channel_text)
            backends = await self._backends(
                service, crn_text or instance_text)
            infos = await self._backend_infos(backends)
            picked = self._pick_from_infos(infos)
            if picked is None:
                self._note_failure(now, "no_backend")
                return _ibm_error_result(
                    code="no_backend", stage="no_backend",
                    reason="no operational hardware QPU",
                    key_present=True, crn_present=crn_present,
                    instance=instance_text, region=region_text,
                    channel=channel_text, checked_at=checked_at)
            if job_store is not None:
                batch = await self._run_durable(
                    api_key=key, crn=crn_text, instance=instance_text,
                    region=region_text, channel=channel_text,
                    length=1, job_store=job_store, supervisor=supervisor,
                    deposit=None, account_key=account_key,
                    config_fp=config_fp, smoke=True,
                    shots_override=shots)
            else:
                instances = await self._instances(service)
                batch = await self._run_on_backend(
                    service=service, backend=picked[0],
                    backend_info=picked[1], shots=shots, requested=1,
                    plan=_ibm_plan_from_instances(
                        instances, crn_text or instance_text),
                    crn=crn_text, region=region_text,
                    channel=channel_text, instance=instance_text,
                    api_key=key)
            self._note_success()
            provenance = dict(batch.provenance or {})
            return {
                "provider": PROVIDER_ID_IBM, "healthy": True, "blocker": None,
                "stage": None, "reason": "",
                "key_present": True, "crn_present": crn_present,
                "instance": instance_text[:120], "region": region_text[:40],
                "channel": channel_text[:48],
                "backend": provenance.get("backend"),
                "job_id": provenance.get("job_id"),
                "shots": provenance.get("shots"),
                "bits": provenance.get("accepted_bits"),
                "values": provenance.get("values"),
                "usage_seconds": provenance.get("usage_seconds"),
                "plan": provenance.get("plan"),
                "is_simulator": False,
                "checked_at": int(time.time()),
            }
        except IbmError as exc:
            self._note_failure(now, exc.code)
            return _ibm_error_result(
                code=exc.code, stage=exc.stage, reason=exc.reason,
                key_present=True, crn_present=crn_present,
                instance=instance_text, region=region_text,
                channel=channel_text, checked_at=checked_at)
        except Exception as exc:
            code = _ibm_error_code(exc)
            self._note_failure(now, code)
            return _ibm_error_result(
                code=code, stage=_ibm_stage_for_code(code),
                reason=_clean_error_text(str(exc), key),
                key_present=True, crn_present=crn_present,
                instance=instance_text, region=region_text,
                channel=channel_text, checked_at=checked_at)

    # ── партия настоящих measurement bits ──────────────────────────────────
    async def fetch(self, *, api_key: str, crn: str = "",
                    instance: str = IBM_INSTANCE_DEFAULT,
                    region: str = IBM_REGION_DEFAULT,
                    channel: str = IBM_CHANNEL,
                    length: int = DEFAULT_BATCH_LENGTH,
                    job_store=None, supervisor=None, deposit=None,
                    account_key: str = "",
                    config_fp: str = "") -> AnuBatch:
        key, crn_text, instance_text, region_text, channel_text = \
            self._validated(api_key, crn, instance, region, channel)
        try:
            length = int(length)
        except (TypeError, ValueError):
            raise IbmError("validation_failed", "bad length", stage="length",
                           sent=False)
        if length < 1:
            raise IbmError("validation_failed", "bad length", stage="length",
                           sent=False)
        now = self._clock()
        self._assert_available(now)
        if job_store is None:
            service = await self._service(
                api_key=key, crn=crn_text, instance=instance_text,
                region=region_text, channel=channel_text)
            backends = await self._backends(
                service, crn_text or instance_text)
            infos = await self._backend_infos(backends)
            picked = self._pick_from_infos(infos)
            if picked is None:
                self._note_failure(now, "no_backend")
                raise IbmError("no_backend", "no operational hardware QPU",
                               stage="no_backend", sent=False)
            instances = await self._instances(service)
            try:
                batch = await self._run_on_backend(
                    service=service, backend=picked[0],
                    backend_info=picked[1],
                    shots=_ibm_shots_for(length, picked[1]["num_qubits"]),
                    requested=length,
                    plan=_ibm_plan_from_instances(
                        instances, crn_text or instance_text),
                    crn=crn_text, region=region_text, channel=channel_text,
                    instance=instance_text)
            except IbmError as exc:
                self._note_failure(self._clock(), exc.code)
                raise
            if deposit is not None:
                batch.provenance["batch_id"] = await deposit(batch)
            self._note_success()
            return batch
        try:
            batch = await self._run_durable(
                api_key=key, crn=crn_text, instance=instance_text,
                region=region_text, channel=channel_text, length=length,
                job_store=job_store, supervisor=supervisor, deposit=deposit,
                account_key=account_key, config_fp=config_fp)
        except IbmError as exc:
            self._note_failure(self._clock(), exc.code)
            raise
        self._note_success()
        return batch

    async def _run_durable(self, *, api_key: str, crn: str, instance: str,
                           region: str, channel: str, length: int,
                           job_store, supervisor, deposit,
                           account_key: str, config_fp: str,
                           smoke: bool = False,
                           shots_override: int | None = None) -> AnuBatch:
        from services.task_supervisor import get_task_supervisor
        sup = supervisor or get_task_supervisor()
        prefix = "random.ibm.smoke" if smoke else "random.ibm.job"
        coalesce = (f"{prefix}:{account_key or 'ibm'}:"
                    f"{config_fp or key_fingerprint(api_key)}")
        # Durability guard ДО submit: активная строка IBM (в т.ч. оставшаяся
        # после рестарта) означает attach/recovery, а не вторую оплату.
        try:
            active = await job_store.active()
        except Exception:
            active = []
        if any(str(r.get("kind") or "") == IBM_JOB_KIND
               for r in active):
            raise IbmError("job_in_progress", "active ibm job exists",
                           retryable=True, sent=False, stage="job")
        box: dict = {}

        async def _job():
            own = await self._find_own_job(job_store, coalesce)
            box["task_job_id"] = own
            batch = await self._submit_and_wait(
                api_key=api_key, crn=crn, instance=instance, region=region,
                channel=channel, length=(1 if smoke else length),
                checkpoint_job_id=own, job_store=job_store,
                purpose=("smoke" if smoke else "refill"),
                shots_override=(shots_override if smoke else None))
            if not smoke and deposit is not None:
                batch.provenance["batch_id"] = await deposit(batch)
            box["batch"] = batch
            return _ibm_external_ref(batch.provenance or {})

        record = await sup.run(
            _job, owner=IBM_JOB_OWNER, kind=IBM_JOB_KIND,
            coalesce_key=coalesce,
            deadline_at=time.time() + self._job_max_age,
            job_store=job_store)
        batch = box.get("batch")
        if batch is None:
            raise IbmError("job_in_progress", "coalesced", retryable=True,
                           sent=False, stage="job",
                           job_state=getattr(record, "status", None))
        return batch

    @staticmethod
    async def _find_own_job(job_store, coalesce: str):
        try:
            rows = await job_store.active()
        except Exception:
            return None
        for row in rows:
            if (str(row.get("kind") or "") == IBM_JOB_KIND
                    and str(row.get("coalesce_key") or "") == coalesce):
                return str(row.get("job_id") or "") or None
        return None

    async def _submit_and_wait(self, *, api_key: str, crn: str,
                               instance: str, region: str, channel: str,
                               length: int, checkpoint_job_id: str | None,
                               job_store=None, purpose: str = "refill",
                               shots_override: int | None = None
                               ) -> AnuBatch:
        service = await self._service(
            api_key=api_key, crn=crn, instance=instance, region=region,
            channel=channel)
        backends = await self._backends(service, crn or instance)
        infos = await self._backend_infos(backends)
        picked = self._pick_from_infos(infos)
        if picked is None:
            raise IbmError("no_backend", "no operational hardware QPU",
                           stage="no_backend", sent=False)
        instances = await self._instances(service)
        plan = _ibm_plan_from_instances(instances, crn or instance)
        return await self._run_on_backend(
            service=service, backend=picked[0], backend_info=picked[1],
            shots=(int(shots_override) if shots_override is not None
                   else _ibm_shots_for(length,
                                       picked[1]["num_qubits"])),
            requested=length, plan=plan, crn=crn, region=region,
            channel=channel, instance=instance, api_key=api_key,
            job_store=job_store, checkpoint_job_id=checkpoint_job_id,
            purpose=purpose)

    async def _wait_job(self, *, job, job_id: str, backend,
                        backend_info: dict, shots: int,
                        num_qubits: int, requested: int,
                        checkpoint_job_id: str | None,
                        submitted_at: int, plan: str | None, crn: str,
                        region: str, channel: str, instance: str,
                        job_store=None, cursor_base: dict | None = None
                        ) -> AnuBatch:
        delay = self._poll_interval
        last_state = None
        while True:
            state = await self._job_state(job) or IBM_JOB_RUNNING
            if state != last_state:
                last_state = state
                fields = dict(cursor_base or {})
                fields.update({"job": job_id, "state": state,
                               "backend": backend_info.get("name"),
                               "instance": instance})
                await self._checkpoint(
                    job_store, checkpoint_job_id, **fields)
            if state == IBM_JOB_COMPLETED:
                try:
                    result = await self._call(job.result)
                except IbmError:
                    raise
                except Exception as exc:
                    code = _ibm_error_code(exc)
                    raise IbmError(code, _clean_error_text(str(exc)),
                                   stage="result", sent=True,
                                   job_state=state)
                actual_backend = _ibm_attr(job, "backend", None)
                if callable(actual_backend):
                    try:
                        actual_backend = await self._call(actual_backend)
                    except Exception:
                        actual_backend = None
                if actual_backend is not None:
                    try:
                        actual_info = await self._call(
                            _ibm_backend_public, actual_backend)
                    except Exception:
                        actual_info = None
                    if actual_info is not None:
                        if actual_info.get("simulator") is not False:
                            raise IbmError(
                                "validation_failed",
                                "simulator backend rejected",
                                stage="backend", sent=True,
                                job_state=state)
                        backend_info = actual_info
                usage, usage_source = await self._job_usage(job)
                return self._batch_from_result(
                    result=result, backend_info=backend_info,
                    job_id=job_id, shots=shots, num_qubits=num_qubits,
                    requested=requested, submitted_at=submitted_at,
                    plan=plan, usage=usage, usage_source=usage_source,
                    crn=crn, region=region, channel=channel,
                    instance=instance)
            if state in (IBM_JOB_FAILED, IBM_JOB_CANCELLED):
                raise IbmError(
                    "provider_unavailable", f"ibm job {state}",
                    stage="job", sent=True, job_state=state)
            age = max(0.0, time.time() - float(submitted_at or 0))
            if age >= self._job_max_age:
                fields = dict(cursor_base or {})
                fields.update({"job": job_id, "state": IBM_JOB_EXPIRED,
                               "backend": backend_info.get("name"),
                               "instance": instance})
                await self._checkpoint(
                    job_store, checkpoint_job_id, **fields)
                raise IbmError("timeout", "ibm job age exceeded",
                               stage="job", retryable=True, sent=True,
                               job_state=IBM_JOB_EXPIRED)
            await self._sleeper(delay)
            if delay > 0:
                delay = min(max(delay * 2, self._poll_interval), 120.0)

    @staticmethod
    async def _checkpoint(job_store, job_id: str | None, **fields) -> None:
        """Durable cursor IBM job через существующий `task_jobs.payload`."""
        if job_store is None or not job_id:
            return
        try:
            cursor = json.dumps(fields, separators=(",", ":"),
                                ensure_ascii=False)
            await job_store.save_checkpoint(
                job_id, cursor_token=cursor, processed=0)
        except Exception:
            # Checkpoint — диагностика/восстановление, не повод ронять job.
            logger.warning("[random_source] ibm checkpoint failed",
                           exc_info=True)

    def _batch_from_result(self, *, result, backend_info: dict,
                           job_id: str, shots: int, num_qubits: int,
                           requested: int, submitted_at: int,
                           plan: str | None, usage: float | None,
                           usage_source: str, crn: str, region: str,
                           channel: str, instance: str) -> AnuBatch:
        if backend_info.get("simulator") is not False:
            raise IbmError("validation_failed",
                           "simulator backend rejected", stage="backend",
                           sent=True)
        if not backend_info.get("name"):
            raise IbmError("validation_failed", "backend name missing",
                           stage="backend", sent=True)
        bitstrings = self._extract_bitstrings(result, shots=shots,
                                              num_qubits=num_qubits)
        bits, stats = _ibm_debias_bitstrings(bitstrings)
        values = _ibm_pack_values(bits, requested)
        if not values:
            raise IbmError("validation_failed",
                           "no unbiased bits extracted", stage="result",
                           sent=True)
        completed_at = int(time.time())
        provenance = {
            "provider": PROVIDER_ID_IBM,
            "channel": channel, "instance": instance,
            "crn_fingerprint": key_fingerprint(crn) if crn else None,
            "region": region, "backend": backend_info.get("name"),
            "job_id": job_id, "batch_id": None,
            "submitted_at": int(submitted_at),
            "completed_at": completed_at,
            "shots": int(shots), "num_qubits": int(num_qubits),
            "raw_bits": stats["raw_bits"], "bias": stats["bias"],
            "pairs": stats["pairs"],
            "accepted_pairs": stats["accepted_pairs"],
            "accepted_bits": stats["unbiased_bits"],
            "values": len(values), "requested_values": int(requested),
            "usage_seconds": usage, "usage_source": usage_source,
            "plan": plan, "is_simulator": False,
            "extraction": "von_neumann_v1",
            "circuit": "h_all+measure_all",
        }
        return AnuBatch(
            values=values, data_type="uint16", length=len(values),
            provider=PROVIDER_ID_IBM,
            latency_ms=max(0, int((time.time() - submitted_at) * 1000)),
            provenance=provenance)

    @staticmethod
    def _extract_bitstrings(result, *, shots: int,
                            num_qubits: int) -> list[str]:
        """Структурная проверка: только настоящие measurement bitstrings."""
        try:
            pub = result[0]
        except Exception:
            raise IbmError("validation_failed", "empty result", stage="result",
                           sent=True)
        data = _ibm_attr(pub, "data", None)
        if data is None:
            raise IbmError("validation_failed", "result data missing",
                           stage="result", sent=True)
        measure = (_ibm_attr(data, "meas", None) if not isinstance(data, dict)
                   else data.get("meas"))
        if measure is None:
            for forbidden in ("quasi_dists", "counts", "statevector"):
                present = (_ibm_attr(data, forbidden, None)
                           if not isinstance(data, dict)
                           else data.get(forbidden))
                if present is not None:
                    raise IbmError(
                        "validation_failed",
                        f"{forbidden} is not measurement bits",
                        stage="result", sent=True)
            raise IbmError("validation_failed", "meas register missing",
                           stage="result", sent=True)
        getter = _ibm_attr(measure, "get_bitstrings", None)
        bitstrings = None
        if callable(getter):
            try:
                bitstrings = list(getter())
            except Exception:
                bitstrings = None
        if bitstrings is None:
            array = _ibm_attr(measure, "array", None)
            if array is not None:
                try:
                    bitstrings = [
                        "".join("1" if int(bit) else "0" for bit in row)
                        for row in array.tolist()]
                except Exception:
                    bitstrings = None
        if not isinstance(bitstrings, list) or len(bitstrings) != int(shots):
            raise IbmError("validation_failed",
                           "shot count mismatch", stage="result", sent=True)
        out: list[str] = []
        for item in bitstrings:
            text = str(item or "").strip()
            if len(text) != int(num_qubits):
                raise IbmError("validation_failed",
                               f"bitstring length: {len(text)}",
                               stage="result", sent=True)
            if any(ch not in "01" for ch in text):
                raise IbmError("validation_failed", "bitstring not binary",
                               stage="result", sent=True)
            out.append(text)
        return out

    async def _run_on_backend(self, *, service, backend,
                              backend_info: dict, shots: int,
                              requested: int, plan: str | None,
                              crn: str = "", region: str = "",
                              channel: str = "", instance: str = "",
                              api_key: str = "", job_store=None,
                              checkpoint_job_id: str | None = None,
                              purpose: str = "refill") -> AnuBatch:
        num_qubits = int(backend_info.get("num_qubits") or 0)
        circuit = self._circuit_factory(num_qubits)
        try:
            circuit = await self._call(self._transpiler, circuit, backend)
        except IbmError:
            raise
        except Exception as exc:
            raise IbmError(
                _ibm_error_code(exc, "validation_failed"),
                _clean_error_text(str(exc), api_key),
                stage="transpile", sent=False)
        job_tag = (f"qrng-p5-{checkpoint_job_id}"
                   if checkpoint_job_id else "")
        await self._checkpoint(
            job_store, checkpoint_job_id, state=IBM_JOB_PENDING,
            instance=instance, backend=backend_info.get("name"),
            shots=shots, qubits=num_qubits, purpose=purpose,
            job_tag=job_tag or None)
        try:
            sampler = await self._call(self._sampler_factory, backend=backend)
            if job_tag:
                try:
                    sampler.options.environment.job_tags = [job_tag]
                except Exception:
                    # Direct/fake sampler без options — job_tag остаётся в
                    # cursor, но не отправляется в IBM.
                    pass
            job = await self._call(sampler.run, [circuit], shots=shots)
        except IbmError:
            raise
        except Exception as exc:
            code = _ibm_error_code(exc)
            raise IbmError(code, _clean_error_text(str(exc), api_key),
                           stage="submit", retryable=True, sent=True)
        job_id = str(getattr(job, "job_id", lambda: "")() or "").strip()
        if not job_id:
            raise IbmError("delivery_unknown", "job id missing",
                           stage="submit", sent=True)
        submitted_at = int(time.time())
        cfg_fp = key_fingerprint("|".join(
            (api_key, crn, instance, region, channel)))
        cursor_base = {
            "job": job_id, "state": IBM_JOB_SUBMITTED,
            "backend": backend_info.get("name"), "instance": instance,
            "shots": shots, "qubits": num_qubits,
            "submitted_at": submitted_at, "values": requested,
            "plan": plan, "config_fp": cfg_fp, "purpose": purpose,
            "job_tag": job_tag or None,
        }
        await self._checkpoint(
            job_store, checkpoint_job_id, **cursor_base)
        return await self._wait_job(
            job=job, job_id=job_id, backend=backend,
            backend_info=backend_info, shots=shots,
            num_qubits=num_qubits, requested=requested,
            checkpoint_job_id=checkpoint_job_id,
            submitted_at=submitted_at, plan=plan,
            crn=crn, region=region, channel=channel, instance=instance,
            job_store=job_store, cursor_base=cursor_base)

    async def find_job_by_tag(self, *, api_key: str, crn: str = "",
                              instance: str = IBM_INSTANCE_DEFAULT,
                              region: str = IBM_REGION_DEFAULT,
                              channel: str = IBM_CHANNEL,
                              tag: str) -> str | None:
        """Найти IBM job по клиентскому tag (submit_uncertain recovery)."""
        key, crn_text, instance_text, region_text, channel_text = \
            self._validated(api_key, crn, instance, region, channel)
        tag_text = str(tag or "").strip()
        if not tag_text:
            return None
        service = await self._service(
            api_key=key, crn=crn_text, instance=instance_text,
            region=region_text, channel=channel_text)
        getter = _ibm_attr(service, "jobs", None)
        if not callable(getter):
            return None
        try:
            jobs = await self._call(
                getter, limit=5, job_tags=[tag_text], descending=True)
        except Exception:
            return None
        for job in jobs or ():
            try:
                job_id = str(getattr(job, "job_id", lambda: "")() or "").strip()
            except Exception:
                job_id = ""
            if job_id:
                return job_id
        return None

    async def resume(self, *, api_key: str, crn: str = "",
                     instance: str = IBM_INSTANCE_DEFAULT,
                     region: str = IBM_REGION_DEFAULT,
                     channel: str = IBM_CHANNEL, job_id: str,
                     shots: int, num_qubits: int, requested: int,
                     submitted_at: int, plan: str | None = None,
                     deposit=None, checkpoint_job_id: str | None = None,
                     job_store=None) -> AnuBatch:
        """Присоединиться к существующему IBM job (без повторной отправки)."""
        key, crn_text, instance_text, region_text, channel_text = \
            self._validated(api_key, crn, instance, region, channel)
        service = await self._service(
            api_key=key, crn=crn_text, instance=instance_text,
            region=region_text, channel=channel_text)
        getter = _ibm_attr(service, "job", None)
        if not callable(getter):
            raise IbmError("provider_unavailable", "job lookup unavailable",
                           stage="attach", sent=False)
        try:
            job = await self._call(getter, job_id)
        except IbmError:
            raise
        except Exception as exc:
            code = _ibm_error_code(exc)
            raise IbmError(code, _clean_error_text(str(exc)),
                           stage="attach", sent=True, job_state="unknown")
        backend = _ibm_attr(job, "backend", None)
        if callable(backend):
            try:
                backend = await self._call(backend)
            except Exception:
                backend = None
        if backend is None:
            raise IbmError("validation_failed", "job backend missing",
                           stage="attach", sent=True)
        try:
            backend_info = await self._call(_ibm_backend_public, backend)
        except Exception:
            backend_info = {"name": _ibm_backend_name(backend),
                            "num_qubits": _ibm_backend_qubits(backend),
                            "simulator": None, "operational": True,
                            "pending_jobs": 0}
        if not num_qubits:
            num_qubits = int(backend_info.get("num_qubits") or 0)
        cursor_base = {
            "job": job_id, "state": IBM_JOB_SUBMITTED,
            "backend": backend_info.get("name"),
            "instance": instance_text,
            "shots": shots, "qubits": num_qubits,
            "submitted_at": submitted_at, "values": requested,
            "plan": plan,
            "config_fp": key_fingerprint("|".join(
                (key, crn_text, instance_text, region_text, channel_text))),
            "purpose": "recovery",
        }
        batch = await self._wait_job(
            job=job, job_id=job_id, backend=backend,
            backend_info=backend_info, shots=shots,
            num_qubits=num_qubits, requested=requested,
            checkpoint_job_id=checkpoint_job_id,
            submitted_at=submitted_at, plan=plan, crn=crn_text,
            region=region_text, channel=channel_text,
            instance=instance_text, job_store=job_store,
            cursor_base=cursor_base)
        if deposit is not None:
            batch.provenance["batch_id"] = await deposit(batch)
        return batch


def _ibm_external_ref(provenance: dict) -> str:
    """Компактный R17-safe provenance для `mca_random_batches.external_ref`."""
    ref = {
        "job": provenance.get("job_id"),
        "batch": provenance.get("batch_id"),
        "backend": provenance.get("backend"),
        "shots": provenance.get("shots"),
        "qubits": provenance.get("num_qubits"),
        "bits": provenance.get("accepted_bits"),
        "values": provenance.get("values"),
        "bias": provenance.get("bias"),
        "pairs": provenance.get("pairs"),
        "acc": provenance.get("accepted_pairs"),
        "usage": provenance.get("usage_seconds"),
        "sub": provenance.get("submitted_at"),
        "done": provenance.get("completed_at"),
        "inst": provenance.get("instance"),
        "crn": provenance.get("crn_fingerprint"),
        "reg": provenance.get("region"),
        "ch": provenance.get("channel"),
        "plan": provenance.get("plan"),
        "sim": False,
    }
    text = json.dumps(ref, separators=(",", ":"), ensure_ascii=False)
    if len(text) > 512:
        # Не обрезаем JSON посередине (иначе late-usage не распарсится):
        # убираем необязательные диагностические поля до валидной длины.
        for key in ("plan", "ch", "reg", "crn", "inst", "done", "sub",
                    "acc", "pairs", "bias", "qubits", "shots"):
            ref.pop(key, None)
            text = json.dumps(ref, separators=(",", ":"),
                              ensure_ascii=False)
            if len(text) <= 512:
                break
    return text[:512] if len(text) <= 512 else json.dumps(
        {"job": ref.get("job"), "backend": ref.get("backend"),
         "values": ref.get("values"), "sim": False},
        separators=(",", ":"), ensure_ascii=False)[:512]


async def ibm_fetch(*, api_key: str, crn: str = "",
                    instance: str = IBM_INSTANCE_DEFAULT,
                    region: str = IBM_REGION_DEFAULT,
                    channel: str = IBM_CHANNEL,
                    length: int = DEFAULT_BATCH_LENGTH,
                    client: IbmQuantumRuntimeClient | None = None,
                    job_store=None, supervisor=None, deposit=None,
                    account_key: str = "", config_fp: str = "") -> AnuBatch:
    """Реестровая точка входа IBM: одна реальная QPU-партия."""
    adapter = client if client is not None else IbmQuantumRuntimeClient()
    return await adapter.fetch(
        api_key=api_key, crn=crn, instance=instance, region=region,
        channel=channel, length=length, job_store=job_store,
        supervisor=supervisor, deposit=deposit, account_key=account_key,
        config_fp=config_fp)


async def ibm_check(*, api_key: str, crn: str = "",
                    instance: str = IBM_INSTANCE_DEFAULT,
                    region: str = IBM_REGION_DEFAULT,
                    channel: str = IBM_CHANNEL,
                    client: IbmQuantumRuntimeClient | None = None) -> dict:
    """Реестровая точка входа read-only проверки IBM (без job/Sampler)."""
    adapter = client if client is not None else IbmQuantumRuntimeClient()
    return await adapter.check_access(
        api_key=api_key, crn=crn, instance=instance, region=region,
        channel=channel)


# P5: IBM подключён к реестру; реестр читается call-time.
PROVIDERS[PROVIDER_ID_IBM] = replace(
    PROVIDERS[PROVIDER_ID_IBM], fetch=ibm_fetch, check=ibm_check)


# ── durable-стор v27 (только через write_transaction mca-01) ───────────────
_DRAW_COLS = (
    "draw_id", "created_at", "chat_id", "purpose", "source", "provider",
    "batch_id", "value", "candidates_json", "pool_size", "probability",
    "policy_version", "selected_id", "fallback_reason", "config_version",
)
_INSERT_DRAW_SQL = (
    "INSERT OR IGNORE INTO mca_random_draws ("
    + ", ".join(_DRAW_COLS) + ") VALUES (" + ",".join("?" * len(_DRAW_COLS))
    + ")")


@dataclass
class ReservedDraw:
    value: int
    index: int | None
    rejected: bool
    batch_id: str
    provider: str
    data_type: str
    draw_id: str
    value_range: int
    created_at: int
    provider_id: str = ""


@dataclass
class ReservedChunkValue:
    value: int
    draw_id: str
    batch_id: str
    provider: str
    data_type: str
    value_range: int
    provider_id: str = ""


class RandomStore:
    """Доступ к v27-таблицам (batches/draws/quota_state/state).

    Каждая запись — `DatabaseService.write_transaction` (единый write-механизм
    mca-01, single-writer). Watermark: `reserved_upto` инкрементируется в ТОЙ
    ЖЕ транзакции, что и journal-запись, ДО использования значения — crash
    может потерять выданное, но повторная выдача исключена."""

    def __init__(self, db) -> None:
        self._db = db

    # ── batches ────────────────────────────────────────────────────────────
    @staticmethod
    def _fingerprint_clause(config_fingerprint: str | None) -> tuple[str, tuple]:
        """Аддитивный фильтр расходования (arch P1 D3, F4 strict).

        `config_fingerprint is None` — без фильтра (внутренние/легаси чтения
        запаса, backfill, тесты store). Строка (в т.ч. пустая) — strict:
        партия расходуется, только если `config_fingerprint IS NULL` (легаси —
        совместимо) ИЛИ равна действующей конфигурации. Пустая действующая
        конфигурация (ключа нет) допускает ТОЛЬКО NULL-партии: партии старого
        ключа после удаления ключа остаются нерасходуемыми."""
        if config_fingerprint is None:
            return "", ()
        fp = str(config_fingerprint).strip()
        if not fp:
            return " AND config_fingerprint IS NULL", ()
        return (" AND (config_fingerprint IS NULL OR config_fingerprint = ?)",
                (fp,))

    @staticmethod
    def _provider_clause(provider_ids) -> tuple[str, tuple]:
        """Аддитивный фильтр провайдера (QRNG P3, arch D5).

        `None` — без фильтра (внутренние/легаси чтения). Кортеж — расходование
        только партий перечисленных провайдеров (канонический id + его
        исторические написания). Неизвестный/пустой набор — пустой SQL-предикат
        (``AND 0``), а не «все провайдеры»: иначе резолв мог бы молча
        израсходовать чужие значения."""
        if provider_ids is None:
            return "", ()
        ids = tuple(str(p) for p in provider_ids if str(p))
        if not ids:
            return " AND 0", ()
        return (" AND provider IN (" + ",".join("?" * len(ids)) + ")", ids)

    @staticmethod
    def _batch_clause(batch_id: str | None) -> tuple[str, tuple]:
        """Аддитивный точный фильтр партии (F-01, активация).

        `batch_id is None` — без фильтра (прежний выбор для refill/dream
        chunk). Строка — только эта партия; пустая строка — пустой
        SQL-предикат (``AND 0``), а не «любая партия»: self-check не должен
        молча израсходовать чужую партию при пустом/потерянном id."""
        if batch_id is None:
            return "", ()
        bid = str(batch_id).strip()
        if not bid:
            return " AND 0", ()
        return " AND batch_id = ?", (bid,)

    async def insert_batch(self, batch: AnuBatch, *,
                           created_at: int | None = None,
                           config_fingerprint: str | None = None,
                           external_ref: str | None = None) -> str:
        batch_id = uuid.uuid4().hex
        values = [int(v) for v in batch.values]
        values_json = json.dumps(values, separators=(",", ":"))
        created = int(created_at if created_at is not None else time.time())
        fp = str(config_fingerprint or "").strip() or None
        ref = str(external_ref or "").strip()[:200] or None

        async def _body(conn):
            await conn.execute(
                "INSERT OR IGNORE INTO mca_random_batches (batch_id, provider, "
                "data_type, length, values_json, reserved_upto, consumed_upto, "
                "source, created_at, config_fingerprint, external_ref) "
                "VALUES (?,?,?,?,?,0,0,'quantum',?,?,?)",
                (batch_id, batch.provider, batch.data_type, len(values),
                 values_json, created, fp, ref))
            return batch_id

        return await self._db.write_transaction(
            _body, op_name="random_batch_insert")

    async def reserve_remaining(self, *,
                                config_fingerprint: str | None = None) -> int:
        clause, params = self._fingerprint_clause(config_fingerprint)
        cursor = await self._db.db.execute(
            "SELECT COALESCE(SUM(length - reserved_upto), 0) AS r "
            "FROM mca_random_batches WHERE reserved_upto < length" + clause,
            params)
        row = await cursor.fetchone()
        return int(row["r"] if row is not None else 0)

    async def provider_reserve(self, *,
                               config_fingerprint: str | None = None) -> dict:
        """Остаток по провайдерам (канонические id; легаси-строки суммируются).

        `config_fingerprint is None` — все партии (внутренний расчёт
        quarantine); строка — strict-фильтр расходования (F4)."""
        clause, params = self._fingerprint_clause(config_fingerprint)
        cursor = await self._db.db.execute(
            "SELECT provider, COALESCE(SUM(length - reserved_upto), 0) AS r "
            "FROM mca_random_batches WHERE reserved_upto < length" + clause
            + " GROUP BY provider", params)
        out: dict[str, int] = {}
        for row in await cursor.fetchall():
            pid = canonical_provider_id(row["provider"])
            if not pid:
                continue
            out[pid] = out.get(pid, 0) + int(row["r"] or 0)
        return out

    async def backfill_config_fingerprint(self, fingerprint: str, *,
                                          provider_ids) -> int:
        """Привязать легаси-партии (NULL) к подтверждённой конфигурации.

        Только NULL-строки и только перечисленные провайдеры: повтор — no-op,
        чужие/уже привязанные партии не меняются, история провайдера не
        переписывается."""
        fp = str(fingerprint or "").strip()
        ids = tuple(str(p) for p in (provider_ids or ()) if str(p))
        if not fp or not ids:
            return 0

        async def _body(conn):
            marks = ",".join("?" * len(ids))
            cursor = await conn.execute(
                "UPDATE mca_random_batches SET config_fingerprint = ? "
                "WHERE config_fingerprint IS NULL AND provider IN ("
                + marks + ")", (fp,) + ids)
            return int(cursor.rowcount or 0)

        return int(await self._db.write_transaction(
            _body, op_name="random_batch_fingerprint_backfill") or 0)

    async def last_batch_info(self) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT batch_id, provider, data_type, length, reserved_upto, "
            "consumed_upto, created_at, config_fingerprint, external_ref "
            "FROM mca_random_batches "
            "ORDER BY created_at DESC, batch_id DESC LIMIT 1")
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def reserve_chunk(self, k: int, *,
                            config_fingerprint: str | None = None,
                            provider_ids=None,
                            batch_id: str | None = None
                            ) -> list[ReservedChunkValue]:
        """Durably зарезервировать bounded chunk значений (D7, mca-06).

        Watermark фиксируется до использования: crash → значения потеряны,
        повторно не выдаются. Журнал для chunk пишется на flush (async-вход).
        `config_fingerprint` — аддитивный фильтр (arch P1 D3);
        `provider_ids` — выбранный селектором провайдер (P3);
        `batch_id` — точная партия (F-01: self-check активации расходует
        только зачисленную партию; `None` — прежний порядок выбора)."""
        k = max(0, int(k))
        if k <= 0:
            return []
        clause, clause_params = self._fingerprint_clause(config_fingerprint)
        provider_sql, provider_params = self._provider_clause(provider_ids)
        batch_sql, batch_params = self._batch_clause(batch_id)
        params = (tuple(clause_params) + tuple(provider_params)
                  + tuple(batch_params))

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT batch_id, provider, data_type, values_json, "
                "reserved_upto, length FROM mca_random_batches "
                "WHERE reserved_upto < length" + clause + provider_sql
                + batch_sql
                + " ORDER BY created_at, batch_id LIMIT 1", params)
            row = await cursor.fetchone()
            if row is None:
                return []
            try:
                values = json.loads(row["values_json"])
            except Exception:
                return []
            start = int(row["reserved_upto"])
            length = int(row["length"])
            take = min(k, max(0, length - start))
            if (take <= 0 or not isinstance(values, list)
                    or len(values) < start + take):
                return []
            updated = await conn.execute(
                "UPDATE mca_random_batches SET reserved_upto = reserved_upto + ? "
                "WHERE batch_id = ? AND reserved_upto = ?",
                (take, row["batch_id"], start))
            if int(updated.rowcount or 0) != 1:
                return []
            value_range = batch_value_range(row["data_type"], values)
            provider_id = canonical_provider_id(row["provider"])
            return [
                ReservedChunkValue(
                    value=int(values[pos]), draw_id=uuid.uuid4().hex,
                    batch_id=row["batch_id"], provider=row["provider"],
                    data_type=row["data_type"], value_range=value_range,
                    provider_id=provider_id)
                for pos in range(start, start + take)]

        return list(await self._db.write_transaction(
            _body, op_name="random_reserve_chunk"))

    async def reserve_draw(self, *, n: int | None,
                           meta: dict,
                           config_fingerprint: str | None = None,
                           provider_ids=None
                           ) -> ReservedDraw | None:
        """Одна транзакция: watermark +1 (до использования) + journal-запись.

        `n=None` — probability-draw (value/range); `n>=2` — index-draw
        (rejection sampling; отвергнутое значение тоже журналируется честно).
        `None` — запаса нет (честная деградация у вызывающего).
        `config_fingerprint` — аддитивный фильтр расходования (arch P1 D3);
        `provider_ids` — выбранный селектором провайдер (P3, arch D5)."""
        created = int(time.time())
        clause, clause_params = self._fingerprint_clause(config_fingerprint)
        provider_sql, provider_params = self._provider_clause(provider_ids)
        params = tuple(clause_params) + tuple(provider_params)

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT batch_id, provider, data_type, values_json, "
                "reserved_upto, length FROM mca_random_batches "
                "WHERE reserved_upto < length" + clause + provider_sql
                + " ORDER BY created_at, batch_id LIMIT 1", params)
            row = await cursor.fetchone()
            if row is None:
                return None
            try:
                values = json.loads(row["values_json"])
            except Exception:
                return None
            start = int(row["reserved_upto"])
            if not isinstance(values, list) or len(values) <= start:
                return None
            value = int(values[start])
            updated = await conn.execute(
                "UPDATE mca_random_batches SET reserved_upto = reserved_upto + 1, "
                "consumed_upto = consumed_upto + 1 "
                "WHERE batch_id = ? AND reserved_upto = ?",
                (row["batch_id"], start))
            if int(updated.rowcount or 0) != 1:
                return None
            value_range = batch_value_range(row["data_type"], values)
            draw_id = uuid.uuid4().hex
            if n is None:
                index, rejected = None, False
                journal_value: Any = (value / value_range
                                      if value_range > 0 else 0.0)
            else:
                index = map_value_to_index(value, int(n), value_range)
                rejected = index is None
                journal_value = value
            await conn.execute(_INSERT_DRAW_SQL, (
                draw_id, created, meta.get("chat_id"),
                meta.get("purpose"), MODE_QUANTUM, row["provider"],
                row["batch_id"], journal_value,
                meta.get("candidates_json"), meta.get("pool_size"),
                meta.get("probability"), meta.get("policy_version"),
                (None if (n is None or rejected) else str(index)),
                meta.get("fallback_reason"), meta.get("config_version")))
            return ReservedDraw(
                value=value, index=index, rejected=rejected,
                batch_id=row["batch_id"], provider=row["provider"],
                data_type=row["data_type"], draw_id=draw_id,
                value_range=value_range, created_at=created,
                provider_id=canonical_provider_id(row["provider"]))

        return await self._db.write_transaction(_body, op_name="random_draw")

    # ── journal ────────────────────────────────────────────────────────────
    async def journal_draw(self, record: dict) -> bool:
        async def _body(conn):
            cursor = await conn.execute(
                _INSERT_DRAW_SQL,
                tuple(record.get(c) for c in _DRAW_COLS))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="random_draw_journal"))

    async def journal_many(self, records: list[dict]) -> int:
        if not records:
            return 0

        async def _body(conn):
            written = 0
            for record in records:
                cursor = await conn.execute(
                    _INSERT_DRAW_SQL,
                    tuple(record.get(c) for c in _DRAW_COLS))
                written += int(cursor.rowcount or 0)
                batch_id = record.get("batch_id")
                if batch_id:
                    await conn.execute(
                        "UPDATE mca_random_batches SET consumed_upto = "
                        "consumed_upto + 1 WHERE batch_id = ? AND "
                        "consumed_upto < length", (batch_id,))
            return written

        return int(await self._db.write_transaction(
            _body, op_name="random_journal_flush"))

    async def recent_draws(self, *, limit: int = 20,
                           chat_id: int | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        sql = ("SELECT " + ", ".join(_DRAW_COLS)
               + " FROM mca_random_draws ")
        params: list[Any] = []
        if chat_id is not None:
            sql += "WHERE chat_id = ? "
            params.append(int(chat_id))
        sql += "ORDER BY created_at DESC, draw_id DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall()]

    async def journal_stats(self) -> dict:
        cursor = await self._db.db.execute(
            "SELECT source, COUNT(*) AS c FROM mca_random_draws "
            "GROUP BY source")
        stats = {"quantum": 0, "pseudorandom": 0}
        for row in await cursor.fetchall():
            stats[str(row["source"])] = int(row["c"])
        return stats

    async def prune(self, *, retention_days: int, max_rows: int) -> int:
        """Bounded-ретенция журнала/партий (env-only; GEN-R8)."""
        cutoff = int(time.time()) - max(1, int(retention_days)) * 86400
        keep = max(1, int(max_rows))

        async def _body(conn):
            removed = 0
            cursor = await conn.execute(
                "DELETE FROM mca_random_draws WHERE created_at < ?", (cutoff,))
            removed += int(cursor.rowcount or 0)
            cursor = await conn.execute(
                "DELETE FROM mca_random_draws WHERE draw_id IN ("
                "SELECT draw_id FROM mca_random_draws ORDER BY created_at "
                "DESC, draw_id DESC LIMIT -1 OFFSET ?)", (keep,))
            removed += int(cursor.rowcount or 0)
            cursor = await conn.execute(
                "DELETE FROM mca_random_batches WHERE reserved_upto >= length "
                "AND created_at < ?", (cutoff,))
            removed += int(cursor.rowcount or 0)
            return removed

        return int(await self._db.write_transaction(
            _body, op_name="random_prune") or 0)

    # ── quota (account-global, не per-chat) ────────────────────────────────
    async def quota_record(self, *, account_key: str, period: str,
                           outcome: str, manual: bool = False,
                           reason: str | None = None) -> None:
        """Period-aware запись квоты (spec §14.3/D3: account_key+period).

        Смена `period` (новый месяц UTC) сбрасывает счётчики прошлого периода
        ДО инкремента — «оценка» не залипает на исчерпании; 429 остаётся
        авторитетной причиной (`last_reason`), `unknown ≠ failed` не меняется."""
        column = {"success": "success", "failed": "failed",
                  "unknown": "unknown"}.get(outcome, "failed")
        now = int(time.time())
        success_at = now if column == "success" else None
        failure_at = now if column in ("failed", "unknown") else None
        same = "mca_random_quota_state.period = excluded.period"

        async def _body(conn):
            await conn.execute(
                "INSERT INTO mca_random_quota_state (account_key, period, "
                "success, failed, unknown, manual_checks, last_success_at, "
                "last_failure_at, last_reason, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(account_key) DO UPDATE SET period=excluded.period, "
                f"success=(CASE WHEN {same} THEN mca_random_quota_state.success "
                "ELSE 0 END) + excluded.success, "
                f"failed=(CASE WHEN {same} THEN mca_random_quota_state.failed "
                "ELSE 0 END) + excluded.failed, "
                f"unknown=(CASE WHEN {same} THEN mca_random_quota_state.unknown "
                "ELSE 0 END) + excluded.unknown, "
                f"manual_checks=(CASE WHEN {same} THEN "
                "mca_random_quota_state.manual_checks ELSE 0 END) + "
                "excluded.manual_checks, "
                f"last_success_at=CASE WHEN {same} THEN "
                "COALESCE(excluded.last_success_at, "
                "mca_random_quota_state.last_success_at) "
                "ELSE excluded.last_success_at END, "
                f"last_failure_at=CASE WHEN {same} THEN "
                "COALESCE(excluded.last_failure_at, "
                "mca_random_quota_state.last_failure_at) "
                "ELSE excluded.last_failure_at END, "
                f"last_reason=CASE WHEN {same} THEN "
                "COALESCE(excluded.last_reason, "
                "mca_random_quota_state.last_reason) "
                "ELSE excluded.last_reason END, "
                "updated_at=excluded.updated_at",
                (str(account_key), str(period),
                 1 if column == "success" else 0,
                 1 if column == "failed" else 0,
                 1 if column == "unknown" else 0,
                 1 if manual else 0, success_at, failure_at,
                 (str(reason)[:160] if reason else None), now))
            return True

        await self._db.write_transaction(_body, op_name="random_quota")

    async def quota_get(self, *, account_key: str) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT account_key, period, success, failed, unknown, "
            "manual_checks, last_success_at, last_failure_at, last_reason, "
            "updated_at FROM mca_random_quota_state WHERE account_key = ?",
            (str(account_key),))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    # ── activation state (одна строка scope='anu') ─────────────────────────
    async def get_state(self) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT scope, key_fingerprint, activation_batch_id, activated_at, "
            "last_fallback_reason, last_fallback_at, updated_at "
            "FROM mca_random_state WHERE scope = 'anu'")
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def write_state(self, **fields) -> None:
        """Частичный upsert: обновляются ТОЛЬКО переданные колонки."""
        allowed = ("key_fingerprint", "activation_batch_id", "activated_at",
                   "last_fallback_reason", "last_fallback_at")
        updates = {k: v for k, v in fields.items() if k in allowed}
        now = int(time.time())

        async def _body(conn):
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                params = list(updates.values()) + [now]
                cursor = await conn.execute(
                    f"UPDATE mca_random_state SET {sets}, updated_at = ? "
                    "WHERE scope = 'anu'", tuple(params))
                if int(cursor.rowcount or 0) > 0:
                    return True
            columns = ["scope", "updated_at"] + list(updates.keys())
            values = ["anu", now] + list(updates.values())
            await conn.execute(
                "INSERT OR REPLACE INTO mca_random_state ("
                + ", ".join(columns) + ") VALUES ("
                + ",".join("?" * len(columns)) + ")", tuple(values))
            return True

        await self._db.write_transaction(_body, op_name="random_state")


# ── результаты draw/политики ────────────────────────────────────────────────
@dataclass
class DrawResult:
    """Результат draw. `deferred=True` — значение не выдано (необязательное
    действие откладывается с честной причиной; чат не блокируется)."""

    index: int | None = None
    value: int | float | None = None
    source: str = MODE_PSEUDORANDOM
    selected_source: str = MODE_QUANTUM
    provider: str | None = None
    provider_id: str | None = None
    entropy_class: str | None = None
    batch_id: str | None = None
    draw_id: str | None = None
    fallback_reason: str | None = None
    reason: str | None = None
    deferred: bool = False
    source_impl: str | None = None
    policy_version: str | None = None
    attempts: int = 1


@dataclass
class PolicyChoice:
    """Нейтральный результат политики 10a (контракт 10b — ExplorationRequest/
    Result создаёт mca-10b; второй контракт здесь не создаётся)."""

    primary: Any
    selected: Any
    explored: bool = False
    reason: str | None = None
    pool: list = field(default_factory=list)
    pool_ids: list = field(default_factory=list)
    draw_ids: list = field(default_factory=list)
    probability: float = DEFAULT_EXPLORATION_PROBABILITY
    policy_version: str = POLICY_VERSION
    source: str | None = None
    fallback_reason: str | None = None
    deferred: bool = False


# ── политика exploration (чистая логика + инъекция источника) ───────────────
class ExplorationPolicy:
    """`choose(primary, alternatives, *, probability, chat_id, purpose,
    policy_version) -> PolicyChoice` (D6/T-4967).

    Семантика:
      * одна probability-проверка на автономную ситуацию (не сумма 5%);
        при успехе — ровно один целостный выбор альтернативы (отдельный draw);
      * exploration-пул БЕЗ основного варианта; нет допустимых альтернатив →
        основной + `no_eligible_alternative` (без draw);
      * равномерный выбор из альтернатив; `policy_version` в журнале;
      * недопустимые измерения не рандомизируются;
      * K4 OFF → primary без probability-draw (причина `disabled`);
      * выбор не обходит уместность/проверку перед отправкой (их выполняет
        потребитель; политика их не подменяет и не отключает)."""

    def __init__(self, source) -> None:
        self._source = source    # RandomSourceService | fake (DI для тестов)

    async def choose(self, primary, alternatives, *, probability: float | None
                     = None, chat_id=None, purpose: str,
                     policy_version: str | None = None,
                     measurement: str | None = None) -> PolicyChoice:
        pv = str(policy_version or POLICY_VERSION)
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_exploration_enabled():
            return PolicyChoice(primary=primary, selected=primary,
                                reason="disabled", policy_version=pv)
        if measurement and str(measurement) in INELIGIBLE_MEASUREMENTS:
            return PolicyChoice(primary=primary, selected=primary,
                                reason="no_eligible_alternative",
                                policy_version=pv)
        if str(purpose or "") not in EXPLORATION_PURPOSES:
            return PolicyChoice(primary=primary, selected=primary,
                                reason="no_eligible_alternative",
                                policy_version=pv)
        pool = [alt for alt in (alternatives or [])
                if not _same_candidate(alt, primary)]
        if not pool:
            return PolicyChoice(primary=primary, selected=primary,
                                reason="no_eligible_alternative",
                                policy_version=pv)
        p = await self._probability(probability, purpose)
        prob_draw = await self._source.draw_probability(
            chat_id=chat_id, purpose=purpose, policy_version=pv,
            probability=p)
        if prob_draw is None or prob_draw.deferred or prob_draw.value is None:
            reason = (prob_draw.reason if prob_draw is not None
                      else "provider_unavailable")
            return PolicyChoice(primary=primary, selected=primary,
                                reason=reason, pool=pool,
                                pool_ids=[_candidate_id(a) for a in pool],
                                probability=p, policy_version=pv,
                                source=(prob_draw.source if prob_draw else None),
                                fallback_reason=(prob_draw.fallback_reason
                                                 if prob_draw else None),
                                deferred=True)
        draw_ids = [d for d in (prob_draw.draw_id,) if d]
        try:
            value = float(prob_draw.value)
        except (TypeError, ValueError):
            value = 1.0
        if value >= p:
            return PolicyChoice(primary=primary, selected=primary,
                                pool=pool,
                                pool_ids=[_candidate_id(a) for a in pool],
                                draw_ids=draw_ids, probability=p,
                                policy_version=pv, source=prob_draw.source,
                                fallback_reason=prob_draw.fallback_reason)
        sel_draw = await self._source.draw_index(
            len(pool), chat_id=chat_id, purpose=purpose, policy_version=pv,
            candidates=[_candidate_id(a) for a in pool], probability=p)
        if sel_draw is None or sel_draw.deferred or sel_draw.index is None:
            reason = (sel_draw.reason if sel_draw is not None
                      else "provider_unavailable")
            return PolicyChoice(primary=primary, selected=primary,
                                reason=reason, pool=pool,
                                pool_ids=[_candidate_id(a) for a in pool],
                                draw_ids=draw_ids, probability=p,
                                policy_version=pv,
                                source=(sel_draw.source if sel_draw else None),
                                fallback_reason=(sel_draw.fallback_reason
                                                 if sel_draw else None),
                                deferred=True)
        index = max(0, min(int(sel_draw.index), len(pool) - 1))
        if sel_draw.draw_id:
            draw_ids.append(sel_draw.draw_id)
        return PolicyChoice(primary=primary, selected=pool[index],
                            explored=True, pool=pool,
                            pool_ids=[_candidate_id(a) for a in pool],
                            draw_ids=draw_ids, probability=p,
                            policy_version=pv, source=sel_draw.source,
                            fallback_reason=sel_draw.fallback_reason)

    async def _probability(self, probability: float | None,
                           purpose: str) -> float:
        if probability is not None:
            try:
                return min(1.0, max(0.0, float(probability)))
            except (TypeError, ValueError):
                pass
        key = EXPLORATION_PROBABILITY_KEYS.get(
            str(purpose or ""), SETTING_EXPLORATION)
        value = await _read_memory_setting(key, None,
                                           DEFAULT_EXPLORATION_PROBABILITY)
        return _as_probability(value, DEFAULT_EXPLORATION_PROBABILITY)


# ── sync-адаптер стыка mca-06 (без fork пайплайна) ──────────────────────────
class CoreDreamRandomSource:
    """`DreamRandomSource` (mca-06): `pick(candidates, *, chat_id, purpose, k)`.

    `pick` — sync, без I/O: маппинг durably зарезервированных значений в
    индексы (rejection sampling) для quantum либо stdlib `random.Random`
    (auto-seed) для pseudorandom. Журнал draw пишется bounded-очередью и
    флашится на следующем async-входе сервиса (crash до флаша: значения
    потеряны, повторно не выдаются; журнал — для завершённых решений).
    `selection_meta` совместим с mca-06 и аддитивен; для quantum `seed=null`
    (честно). «Выбор ≠ вердикт»: вердикт downstream — только по доказательствам.
    """

    def __init__(self, *, pipeline_run_id: int | None = None,
                 chat_id: int | None = None, source: str = MODE_QUANTUM,
                 provider: str | None = None, batch_id: str | None = None,
                 data_type: str = DEFAULT_DATA_TYPE, values=(),
                 draw_ids=(), fallback: bool = False,
                 fallback_reason: str | None = None,
                 journal_sink: Callable[[dict], None] | None = None) -> None:
        self.pipeline_run_id = pipeline_run_id
        self.chat_id = chat_id
        self.source = str(source)
        self.provider = provider
        self.batch_id = batch_id
        self.data_type = str(data_type)
        self.values = [int(v) for v in values]
        self.draw_ids = [str(d) for d in draw_ids]
        self.fallback = bool(fallback)
        self.fallback_reason = fallback_reason
        self._journal_sink = journal_sink

    def pick(self, candidates, *, chat_id, purpose: str, k: int
             ) -> tuple[list, dict]:
        pool = list(candidates or [])
        n = len(pool)
        k = max(0, min(int(k), n))
        picked: list[int] = []
        used: list[tuple[int, str | None, int | None]] = []  # value, draw_id, idx
        if k > 0 and n > 0:
            if self.source == MODE_QUANTUM:
                value_range = batch_value_range(self.data_type, self.values)
                for pos, value in enumerate(self.values):
                    if len(picked) >= k:
                        break
                    draw_id = (self.draw_ids[pos]
                               if pos < len(self.draw_ids) else None)
                    index = map_value_to_index(int(value), n, value_range)
                    used.append((int(value), draw_id, index))
                    if index is None or index in picked:
                        continue
                    picked.append(index)
            else:
                rng = random.Random()      # auto-seed; не для security
                picked = sorted(rng.sample(range(n), k))
                for index in picked:
                    used.append((int(index), uuid.uuid4().hex, int(index)))
        else:
            picked = []
        picked = sorted(picked)
        items = [pool[i] for i in picked]
        quantum = self.source == MODE_QUANTUM
        provider_id = canonical_provider_id(self.provider) if quantum else ""
        meta: dict[str, Any] = {
            "source": ("quantum" if quantum else "pseudorandom"),
            "purpose": str(purpose),
            "seed": None,
            "k": int(k),
            "pool": int(n),
            "picked": [int(i) for i in picked][:SELECTION_META_CAP],
            "provider": (self.provider if quantum else PROVIDER_PRNG),
            # Provenance (arch P1 G4/D1): канонический id + класс энтропии
            # из реестра; `source_impl` производный, а не хардкод "anu-quantum".
            "provider_id": provider_id or None,
            "entropy_class": (entropy_class_for(provider_id)
                              if quantum else None),
            "batch_id": (self.batch_id if quantum else None),
            "draw_ids": [d for _, d, _ in used if d][:SELECTION_META_CAP],
            "fallback": bool(self.fallback),
            "fallback_reason": self.fallback_reason,
            "source_impl": (SOURCE_IMPL_PRNG if not quantum
                            else source_impl_for(provider_id)),
            "reserved": len(self.values),
            "used": len(used),
        }
        if self._journal_sink is not None and used:
            candidates_json = json.dumps(
                [_candidate_id(c) for c in pool[:CANDIDATES_CAP]],
                ensure_ascii=False)
            for value, draw_id, index in used:
                try:
                    self._journal_sink({
                        "draw_id": draw_id or uuid.uuid4().hex,
                        "created_at": int(time.time()),
                        "chat_id": (int(chat_id)
                                    if chat_id is not None else None),
                        "purpose": str(purpose)[:120],
                        "source": meta["source"],
                        "provider": meta["provider"],
                        "batch_id": meta["batch_id"],
                        "value": int(value),
                        "candidates_json": candidates_json,
                        "pool_size": int(n),
                        "probability": None,
                        "policy_version": POLICY_VERSION,
                        "selected_id": (str(index) if index is not None
                                        else None),
                        "fallback_reason": self.fallback_reason,
                        "config_version": APP_VERSION,
                    })
                except Exception:      # sink fail-safe: pick не рвём
                    break
        return items, meta


# ── сервис ──────────────────────────────────────────────────────────────────
def _as_mode(value, default: str = DEFAULT_SOURCE) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODES else default


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_probability(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:       # NaN
        return default
    return min(1.0, max(0.0, number))


def _as_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum or number > maximum:
        return default
    return number


async def _read_memory_setting(key: str, chat_id, default):
    """Единственный read-path настроек (`worker_settings.resolve_setting`);
    fail-open: ошибка чтения → дефолт (бот жив), значение в лог не попадает."""
    try:
        from services.worker_settings import resolve_setting
        return await resolve_setting(key, chat_id=chat_id, default=default)
    except Exception:
        logger.warning("[random_source] setting read failed — default | "
                       "key=%s", key)
        return default


def _hot_setting(key: str, default):
    """Глобальный слой (bot_settings/ConfigCache) с fail-open на дефолт."""
    try:
        from services import hot_config as hot
        value = hot.get(key, None)
    except Exception:
        value = None
    return default if value is None else value


@dataclass
class ProviderResolution:
    """Действующий выбор провайдера (QRNG P3, arch D5) — без расхода значений.

    `primary_setting_raw` — сохранённое значение КАК ЕСТЬ (для честного
    `requires_resolution`); `primary_provider` — канонический id, который
    реально возглавляет порядок (заводской IBM при отсутствии/снятом
    значении). `resolved_primary` — первый доступный провайдер (сконфигурирован
    ИЛИ имеет расходуемый запас текущей конфигурации); `effective_provider` —
    тот, из чьего запаса будет взято следующее значение (только расходуемый
    запас); `mode` — quantum | pseudorandom | deferred."""

    mode: str
    selected_mode: str
    primary_provider: str | None
    primary_setting_raw: str
    primary_setting_state: str
    resolved_primary: str | None
    effective_provider: str | None
    fallback_enabled: bool
    fallback_order: tuple[str, ...]
    effective_order: tuple[str, ...]
    blocker: str | None
    fallback_order_raw: Any = None
    fallback_order_state: str = PRIMARY_SETTING_ABSENT


class RandomSourceService:
    """Единственный сервис RandomSource (D1–D5)."""

    def __init__(self, db=None, *, client: AnuClient | None = None,
                 auto_refill: bool = True,
                 clock: Callable | None = None) -> None:
        self.db = db
        self._store = RandomStore(db) if db is not None else None
        self._client = client
        self._client_pinned = client is not None
        self._auto_refill = bool(auto_refill)
        self._policy = ExplorationPolicy(source=self)
        self._journal_queue: collections.deque = collections.deque(
            maxlen=JOURNAL_QUEUE_MAX)
        self._journal_dropped = 0
        self._transition_key: str | None = None
        self._refill_task: asyncio.Task | None = None
        self._check_lock = asyncio.Lock()
        self._check_task: asyncio.Task | None = None
        self._check_key: str | None = None
        self._last_latency_ms: int | None = None
        self._last_refill_reason: str | None = None
        # QRNG P1 (G14/D8): cooldown ручных проверок — расширение
        # существующего singleflight, отдельного планировщика нет.
        self._clock = clock or time.monotonic
        self._recent_checks: dict[str, tuple[float, dict]] = {}
        # QRNG P3 (arch D5/D9, N1): ОДИН общий LfdrClient на сервис —
        # breaker/min-interval сохраняются между refill/проверками (второй
        # клиент/второй контур не создаются). Состояние здоровья — in-memory
        # диагностика с момента старта (ANU durable-состояние `mca_random_state`
        # остаётся ANU-scoped, G16; LfDR его не пишет).
        self._lfdr_client: LfdrClient | None = None
        self._lfdr_client_pinned = False
        self._lfdr_health: dict[str, Any] = {
            "state": ANU_STATE_UNVERIFIED, "last_error": None,
            "last_success_at": None, "last_failure_at": None,
        }
        # QRNG P5: ОДИН общий IBM-клиент сервиса (breaker/health — in-memory,
        # ANU durable state не перезаписывается). Durable job'ы — существующие
        # task_jobs; второго store/планировщика нет.
        self._ibm_client: IbmQuantumRuntimeClient | None = None
        self._ibm_client_pinned = False
        self._ibm_health: dict[str, Any] = {
            "state": ANU_STATE_UNVERIFIED, "last_error": None,
            "last_stage": None, "last_success_at": None,
            "last_failure_at": None, "last_job": None, "plan": None,
            "usage": None, "config_fp": None,
        }
        self._ibm_recovery_tasks: set[asyncio.Task] = set()
        self._ibm_recovering: set[str] = set()
        self._ibm_smoke_lock = asyncio.Lock()
        self._ibm_smoke_task: asyncio.Task | None = None
        self._ibm_smoke_key: str | None = None
        self._ibm_smoke_recent: dict[str, tuple[float, dict]] = {}

    # ── DI/жизненный цикл ──────────────────────────────────────────────────
    def bind_db(self, db) -> None:
        self.db = db
        self._store = RandomStore(db) if db is not None else None

    def set_client(self, client: AnuClient | None) -> None:
        self._client = client
        self._client_pinned = client is not None

    def _get_client(self) -> AnuClient:
        if self._client is None:
            self._client = AnuClient(
                timeout=self._timeout_seconds(),
                min_interval=mca_gates.random_min_request_interval_seconds(),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()))
        elif not self._client_pinned:
            self._client.configure(
                timeout=self._timeout_seconds(),
                min_interval=mca_gates.random_min_request_interval_seconds(),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()))
        return self._client

    def set_lfdr_client(self, client: LfdrClient | None) -> None:
        """Инъекция общего LfDR-клиента (тесты/DI); None — сброс."""
        self._lfdr_client = client
        self._lfdr_client_pinned = client is not None

    def _get_lfdr_client(self) -> LfdrClient:
        """Единственный LfDR-клиент сервиса (N1: breaker/min-interval общие).

        Конфигурация — существующие env-гейты (те же, что у ANU); новых
        настроек/эндпоинтов нет."""
        if self._lfdr_client is None:
            self._lfdr_client = LfdrClient(
                timeout=self._timeout_seconds(),
                min_interval=mca_gates.random_min_request_interval_seconds(),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()),
                clock=self._clock)
        elif not self._lfdr_client_pinned:
            self._lfdr_client.configure(
                timeout=self._timeout_seconds(),
                min_interval=mca_gates.random_min_request_interval_seconds(),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()))
        return self._lfdr_client

    def set_ibm_client(self, client: IbmQuantumRuntimeClient | None) -> None:
        """Инъекция общего IBM-клиента (тесты/DI); None — сброс."""
        self._ibm_client = client
        self._ibm_client_pinned = client is not None

    def _get_ibm_client(self) -> IbmQuantumRuntimeClient:
        """Единственный IBM-клиент сервиса (breaker/health общие)."""
        if self._ibm_client is None:
            self._ibm_client = IbmQuantumRuntimeClient(
                timeout=float(self._ibm_http_timeout()),
                poll_interval=float(self._ibm_poll_interval()),
                job_max_age=float(self._ibm_job_max_age()),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()),
                clock=self._clock)
        elif not self._ibm_client_pinned:
            self._ibm_client.configure(
                timeout=float(self._ibm_http_timeout()),
                poll_interval=float(self._ibm_poll_interval()),
                job_max_age=float(self._ibm_job_max_age()),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()))
        return self._ibm_client

    # ── IBM: настройки/секреты (global; значения не логируются) ────────────
    def _ibm_api_key(self) -> str:
        raw = _hot_setting(SETTING_IBM_KEY, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_IBM_API_KEY", "") or ""
        return str(raw or "").strip()

    def _ibm_crn(self) -> str:
        raw = _hot_setting(SETTING_IBM_CRN, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_IBM_CRN", "") or ""
        return str(raw or "").strip()

    def _ibm_instance(self) -> str:
        raw = _hot_setting(SETTING_IBM_INSTANCE, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_IBM_INSTANCE",
                          IBM_INSTANCE_DEFAULT)
        return str(raw or IBM_INSTANCE_DEFAULT).strip()

    def _ibm_region(self) -> str:
        raw = _hot_setting(SETTING_IBM_REGION, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_IBM_REGION", IBM_REGION_DEFAULT)
        return str(raw or IBM_REGION_DEFAULT).strip()

    def _ibm_channel(self) -> str:
        raw = _hot_setting(SETTING_IBM_CHANNEL, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_IBM_CHANNEL", IBM_CHANNEL)
        return str(raw or IBM_CHANNEL).strip()

    def _ibm_http_timeout(self) -> int:
        return _as_int(_hot_setting(SETTING_IBM_HTTP_TIMEOUT,
                                    DEFAULT_IBM_HTTP_TIMEOUT_SECONDS),
                       DEFAULT_IBM_HTTP_TIMEOUT_SECONDS, 1, 120)

    def _ibm_poll_interval(self) -> int:
        return _as_int(_hot_setting(SETTING_IBM_POLL_INTERVAL,
                                    DEFAULT_IBM_POLL_INTERVAL_SECONDS),
                       DEFAULT_IBM_POLL_INTERVAL_SECONDS, 1, 300)

    def _ibm_job_max_age(self) -> int:
        return _as_int(_hot_setting(SETTING_IBM_JOB_MAX_AGE,
                                    DEFAULT_IBM_JOB_MAX_AGE_SECONDS),
                       DEFAULT_IBM_JOB_MAX_AGE_SECONDS, 60, 21600)

    def _ibm_max_inflight(self) -> int:
        return _as_int(_hot_setting(SETTING_IBM_MAX_INFLIGHT,
                                    DEFAULT_IBM_MAX_INFLIGHT),
                       DEFAULT_IBM_MAX_INFLIGHT, 1, 2)

    def _ibm_max_jobs_per_day(self) -> int:
        return _as_int(_hot_setting(SETTING_IBM_MAX_JOBS_PER_DAY,
                                    DEFAULT_IBM_MAX_JOBS_PER_DAY),
                       DEFAULT_IBM_MAX_JOBS_PER_DAY, 0, 100)

    def _ibm_max_qpu_seconds_per_day(self) -> int:
        return _as_int(_hot_setting(SETTING_IBM_MAX_QPU_SECONDS_PER_DAY,
                                    DEFAULT_IBM_MAX_QPU_SECONDS_PER_DAY),
                       DEFAULT_IBM_MAX_QPU_SECONDS_PER_DAY, 0, 3600)

    def _ibm_config_fingerprint(self) -> str:
        """Fingerprint действующей IBM-конфигурации (без секретов наружу)."""
        raw = "|".join((self._ibm_api_key(), self._ibm_crn(),
                        self._ibm_instance(), self._ibm_region(),
                        self._ibm_channel()))
        return key_fingerprint(raw) if raw.strip("|") else ""

    def _ibm_account_key(self) -> str:
        return f"ibm:{self._ibm_instance().lower()}"

    def _ibm_configured(self) -> bool:
        return bool(self._ibm_api_key() and (
            self._ibm_crn() or self._ibm_instance())
            and self._ibm_channel() == IBM_CHANNEL)

    def _ibm_dependency_available(self) -> bool:
        # Pinned client (DI/тесты) доказывает доступность адаптера независимо
        # от установленного пакета; в продакшене проверяется реальный import.
        if self._ibm_client is not None and self._ibm_client_pinned:
            return True
        return _qiskit_runtime_available()

    # ── настройки (per-call; hot; валидация на чтении) ─────────────────────
    async def selected_mode(self, chat_id=None) -> str:
        raw = await _read_memory_setting(SETTING_SOURCE, chat_id,
                                         DEFAULT_SOURCE)
        mode = _as_mode(raw, DEFAULT_SOURCE)
        if mode != str(raw or "").strip().lower() and str(raw or "").strip():
            logger.warning("[random_source] invalid mode — default | "
                           "value=%s", str(raw)[:20])
        return mode

    async def fallback_enabled(self, chat_id=None) -> bool:
        raw = await _read_memory_setting(SETTING_FALLBACK, chat_id,
                                         DEFAULT_FALLBACK)
        return _as_bool(raw, DEFAULT_FALLBACK)

    # ── QRNG P3: селектор провайдера (глобальный слой) ─────────────────────
    def _primary_setting_raw(self) -> str:
        """Сохранённое `random.primary_provider` как есть (глобально)."""
        raw = _hot_setting(SETTING_PRIMARY_PROVIDER, None)
        return str(raw or "").strip()

    def _provider_fallback_enabled(self) -> bool:
        """`random.fallback_enabled` — фолбэк ПО ПРОВАЙДЕРАМ (не PRNG).

        Отдельная ось от `memory.random_fallback_to_pseudorandom`: PRNG не
        входит в порядок и не включается этим переключателем."""
        raw = _hot_setting(SETTING_PROVIDER_FALLBACK_ENABLED,
                           DEFAULT_PROVIDER_FALLBACK_ENABLED)
        return _as_bool(raw, DEFAULT_PROVIDER_FALLBACK_ENABLED)

    def _fallback_order_saved(self) -> list[str]:
        """Сохранённый `random.fallback_order` → канонические id (read-only)."""
        return normalize_fallback_order(self._fallback_order_raw())

    def _fallback_order_raw(self):
        """Сырое сохранённое `random.fallback_order` (None — строки нет)."""
        return _hot_setting(SETTING_FALLBACK_ORDER, None)

    def provider_configured(self, provider_id: str) -> bool:
        """Есть ли у провайдера всё необходимое для запросов (НЕ health).

        ANU — действующий ключ; LfDR — ключ не требуется (документированный
        публичный endpoint, адаптер P2); IBM — key + instance/CRN + разрешённый
        channel (P5). Наличие полей НЕ считается успешной проверкой."""
        pid = str(provider_id or "")
        if pid == PROVIDER_ID_ANU:
            return bool(self._resolve_key())
        if pid == PROVIDER_ID_LFDR:
            return True
        if pid == PROVIDER_ID_IBM:
            return self._ibm_configured()
        return False

    def _lfdr_state(self) -> str:
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return ANU_STATE_DISABLED
        state = str(self._lfdr_health.get("state") or ANU_STATE_UNVERIFIED)
        if self._lfdr_client is not None:
            status = self._lfdr_client.status()
            if float(status.get("circuit_open_until") or 0.0) > self._clock():
                return ANU_STATE_DEGRADED
        return state

    def _lfdr_blocker(self) -> str:
        return str(self._lfdr_health.get("last_error") or "provider_unavailable")

    def _note_lfdr_success(self, *, latency_ms: int | None = None) -> None:
        self._lfdr_health = {
            "state": ANU_STATE_ACTIVE, "last_error": None,
            "last_success_at": int(time.time()),
            "last_failure_at": self._lfdr_health.get("last_failure_at"),
            "latency_ms": latency_ms,
        }

    def _note_lfdr_failure(self, code: str) -> None:
        self._lfdr_health = {
            "state": ANU_STATE_DEGRADED, "last_error": str(code)[:80],
            "last_success_at": self._lfdr_health.get("last_success_at"),
            "last_failure_at": int(time.time()),
            "latency_ms": self._lfdr_health.get("latency_ms"),
        }

    def _ibm_state(self) -> str:
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return ANU_STATE_DISABLED
        if not self._ibm_api_key():
            return ANU_STATE_UNCONFIGURED
        if not (self._ibm_crn() or self._ibm_instance()):
            return ANU_STATE_UNCONFIGURED
        if self._ibm_channel() != IBM_CHANNEL:
            return ANU_STATE_DEGRADED
        if not self._ibm_dependency_available():
            return ANU_STATE_DEGRADED
        health_fp = str(self._ibm_health.get("config_fp") or "")
        if health_fp and health_fp != self._ibm_config_fingerprint():
            return ANU_STATE_UNVERIFIED
        state = str(self._ibm_health.get("state") or ANU_STATE_UNVERIFIED)
        if self._ibm_client is not None:
            status = self._ibm_client.status()
            if float(status.get("circuit_open_until") or 0.0) > self._clock():
                return ANU_STATE_DEGRADED
        return state

    def _ibm_blocker(self) -> str:
        if not self._ibm_api_key() or not (
                self._ibm_crn() or self._ibm_instance()):
            return "provider_unconfigured"
        if self._ibm_channel() != IBM_CHANNEL:
            return "invalid_channel"
        if not self._ibm_dependency_available():
            return "dependency_missing"
        health_fp = str(self._ibm_health.get("config_fp") or "")
        if health_fp and health_fp != self._ibm_config_fingerprint():
            # Ошибка относилась к старой конфигурации — не выдаём её за
            # текущее состояние.
            return "provider_unavailable"
        return str(self._ibm_health.get("last_error")
                   or "provider_unavailable")

    def _note_ibm_success(self, *, latency_ms: int | None = None,
                          job: dict | None = None,
                          plan: str | None = None,
                          usage: dict | None = None) -> None:
        self._ibm_health = {
            "state": ANU_STATE_ACTIVE,
            "last_error": None,
            "last_stage": None,
            "last_success_at": int(time.time()),
            "last_failure_at": self._ibm_health.get("last_failure_at"),
            "latency_ms": latency_ms,
            "last_job": job or self._ibm_health.get("last_job"),
            "plan": plan if plan is not None
            else self._ibm_health.get("plan"),
            "usage": usage if usage is not None
            else self._ibm_health.get("usage"),
            "config_fp": self._ibm_config_fingerprint(),
        }

    def _note_ibm_failure(self, code: str, *,
                          stage: str | None = None) -> None:
        self._ibm_health = {
            "state": ANU_STATE_DEGRADED,
            "last_error": str(code)[:80],
            "last_stage": str(stage or "")[:40] or None,
            "last_success_at": self._ibm_health.get("last_success_at"),
            "last_failure_at": int(time.time()),
            "latency_ms": self._ibm_health.get("latency_ms"),
            "last_job": self._ibm_health.get("last_job"),
            "plan": self._ibm_health.get("plan"),
            "usage": self._ibm_health.get("usage"),
            "config_fp": self._ibm_config_fingerprint(),
        }

    async def exploration_probability(self, purpose: str,
                                      chat_id=None) -> float:
        key = EXPLORATION_PROBABILITY_KEYS.get(str(purpose or ""),
                                                SETTING_EXPLORATION)
        raw = await _read_memory_setting(key, chat_id,
                                         DEFAULT_EXPLORATION_PROBABILITY)
        return _as_probability(raw, DEFAULT_EXPLORATION_PROBABILITY)

    def _resolve_key(self) -> str:
        raw = _hot_setting(SETTING_KEY, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_QUANTUM_API_KEY", "") or ""
        return str(raw or "").strip()

    def _endpoint(self) -> str:
        return str(_hot_setting(SETTING_ENDPOINT, ANU_ENDPOINT) or "").strip()

    def _plan(self) -> str:
        raw = str(_hot_setting(SETTING_PLAN, DEFAULT_PLAN) or "").strip()
        return raw if raw in PLANS else DEFAULT_PLAN

    def _batch_length(self) -> int:
        return _as_int(_hot_setting(SETTING_BATCH_LENGTH, DEFAULT_BATCH_LENGTH),
                       DEFAULT_BATCH_LENGTH, MIN_LENGTH, MAX_LENGTH)

    def _data_type(self) -> str:
        raw = str(_hot_setting(SETTING_DATA_TYPE, DEFAULT_DATA_TYPE)
                  or "").strip().lower()
        return raw if raw in DATA_TYPES else DEFAULT_DATA_TYPE

    def _timeout_seconds(self) -> float:
        return float(_as_int(_hot_setting(SETTING_TIMEOUT,
                                          DEFAULT_TIMEOUT_SECONDS),
                             DEFAULT_TIMEOUT_SECONDS, 1, 30))

    def _low_watermark(self) -> int:
        buffer_max = self._buffer_max()
        return _as_int(_hot_setting(SETTING_LOW_WATERMARK,
                                    DEFAULT_LOW_WATERMARK),
                       DEFAULT_LOW_WATERMARK, 1, buffer_max)

    def _buffer_max(self) -> int:
        return _as_int(_hot_setting(SETTING_BUFFER_MAX, DEFAULT_BUFFER_MAX),
                       DEFAULT_BUFFER_MAX, 256, 8192)

    def _account_key(self) -> str:
        return f"anu:{self._plan().lower()}"

    # ── журнал (bounded-очередь sync-pick + flush на async-входе) ──────────
    def _enqueue_journal(self, record: dict) -> None:
        try:
            if len(self._journal_queue) >= JOURNAL_QUEUE_MAX:
                self._journal_dropped += 1
            self._journal_queue.append(record)
        except Exception:          # pragma: no cover - защитная ветка
            pass

    async def flush_journal(self) -> int:
        if not self._journal_queue or self._store is None:
            return 0
        batch = list(self._journal_queue)
        self._journal_queue.clear()
        try:
            return await self._store.journal_many(batch)
        except Exception:
            logger.warning("[random_source] journal flush failed | "
                           "count=%d", len(batch), exc_info=True)
            for record in batch:
                self._enqueue_journal(record)
            return 0

    def journal_queue_depth(self) -> int:
        return len(self._journal_queue)

    # ── события (notable-only, единый emit_mca_event) ──────────────────────
    def _emit(self, event_name: str, *, outcome: str, level: str = "INFO",
              reason_code: str | None = None, **fields) -> None:
        if not mca_gates.random_source_enabled():
            return
        try:
            mca_events.emit_mca_event(
                event_name, outcome=outcome, level=level,
                component="random", reason_code=reason_code, **fields)
        except Exception:          # pragma: no cover - fail-open
            return

    def _note_transition(self, *, key: str, reason: str,
                         deferred: bool = False) -> None:
        """Один notable-переход (не на каждый draw): random_fallback."""
        if self._transition_key == key:
            return
        self._transition_key = key
        self._emit("random_fallback", outcome=mca_events.OUTCOME_SILENT,
                   level=mca_events.LEVEL_WARN,
                   reason_code="random_fallback" if not deferred else reason,
                   stage="fallback",
                   entity_ids={"blocker": reason, "deferred": bool(deferred)})

    def _note_quantum_success(self) -> None:
        self._transition_key = None

    # ── резолв selected/effective (без расхода значений) ───────────────────
    def _current_fingerprint(self) -> str:
        """Fingerprint действующей конфигурации провайдера (P1: ANU-ключ).

        Пусто — ключа нет: strict-фильтр (F4) допускает только NULL-партии
        (легаси), партии удалённого ключа остаются нерасходуемыми; новых
        запросов без ключа нет. Секрет/ключ наружу не отдаётся — только
        `sha256(key)[:12]`."""
        key = self._resolve_key()
        return key_fingerprint(key) if key else ""

    def _provider_fingerprint(self, provider_id: str) -> str:
        """Fingerprint конфигурации конкретного провайдера (изоляция партий).

        ANU — ключ ANU; LfDR — пусто (партии NULL); IBM — key+CRN+instance+
        region+channel. Значения секретов наружу не попадают."""
        pid = str(provider_id or "")
        if pid == PROVIDER_ID_ANU:
            return self._current_fingerprint()
        if pid == PROVIDER_ID_IBM:
            return self._ibm_config_fingerprint()
        return ""

    async def resolve_selection(self, chat_id=None) -> ProviderResolution:
        """Действующий выбор источника (arch D5/D6) — без расхода значений.

        Порядок: primary → `random.fallback_order` (если fallback включён).
        Провайдер «доступен», если сконфигурирован и/или имеет расходуемый
        запас действующей конфигурации; иначе — следующий. Снятое/неизвестное
        сохранённое значение (`requires_resolution`) НЕ действует и НЕ
        подменяется молча: применяется канонический порядок IBM→ANU→LfDR, а
        сырое значение остаётся в `primary_setting_raw`.

        `mode`: quantum — есть провайдер с расходуемым запасом; pseudorandom —
        квантового запаса нет, но PRNG-откат явно разрешён настройкой;
        deferred — ни квантового источника, ни разрешённого PRNG (не quantum,
        не PRNG)."""
        selected = await self.selected_mode(chat_id)
        raw = self._primary_setting_raw()
        state = primary_setting_state(raw)
        fallback_on = self._provider_fallback_enabled()
        raw_order = self._fallback_order_raw()
        saved_order = normalize_fallback_order(raw_order)
        order_state = fallback_order_state(raw_order)
        # Снятое значение не действует: голова порядка — канонический IBM,
        # и сохранённый fallback_order под недействительную настройку не
        # применяется (arch P3/EXC-03).
        primary_canonical = canonical_provider_id(raw) or None
        order_source = saved_order
        if state == PRIMARY_SETTING_REQUIRES_RESOLUTION:
            primary_canonical = None
            order_source = []
        elif raw_order is None:
            # Строки нет — действует заводской хвост (ANU→LfDR после IBM).
            order_source = list(DEFAULT_FALLBACK_ORDER)
        effective = build_effective_order(primary_canonical, order_source,
                                          fallback_on)
        primary_head = effective[0] if effective else None
        resolved: str | None = None
        effective_provider: str | None = None
        blocker: str | None = None
        if selected == MODE_PSEUDORANDOM:
            mode = MODE_PSEUDORANDOM
        elif not mca_gates.random_quantum_enabled():
            mode = MODE_PSEUDORANDOM
            blocker = "disabled"
        else:
            reserve = await self._provider_reserve_map()
            for pid in effective:
                configured = self.provider_configured(pid)
                has_reserve = int(reserve.get(pid, 0) or 0) > 0
                if resolved is None and (configured or has_reserve):
                    resolved = pid
                if effective_provider is None and has_reserve:
                    effective_provider = pid
            if effective_provider is not None:
                mode = MODE_QUANTUM
            elif await self.fallback_enabled(chat_id):
                mode = MODE_PSEUDORANDOM
            else:
                mode = "deferred"
            if effective_provider is None:
                blocker = await self._resolution_blocker(resolved)
        return ProviderResolution(
            mode=mode, selected_mode=selected, primary_provider=primary_head,
            primary_setting_raw=raw, primary_setting_state=state,
            resolved_primary=resolved, effective_provider=effective_provider,
            fallback_enabled=bool(fallback_on),
            fallback_order=tuple(effective[1:]),
            effective_order=tuple(effective), blocker=blocker,
            fallback_order_raw=raw_order, fallback_order_state=order_state)

    async def resolve_effective(self, chat_id=None) -> tuple[str, str | None]:
        """(effective, blocker) — совместимый фасад `resolve_selection`.

        quantum — только при K1/K2 ON, выбранном quantum и расходуемом запасе
        выбранного провайдера; pseudorandom — явный PRNG-откат; deferred —
        ни квантового источника, ни разрешённого PRNG."""
        result = await self.resolve_selection(chat_id)
        return result.mode, result.blocker

    async def _resolution_blocker(self, resolved: str | None) -> str:
        """Причина отсутствия квантового значения при выбранном провайдере."""
        if resolved == PROVIDER_ID_ANU:
            return await self._provider_blocker()
        if resolved == PROVIDER_ID_LFDR:
            return self._lfdr_blocker()
        if resolved == PROVIDER_ID_IBM:
            return self._ibm_blocker()
        return "provider_unconfigured"

    async def _provider_reserve_map(self) -> dict:
        """Расходуемый остаток по провайдерам ИХ действующих конфигураций.

        Один общий fingerprint здесь неверен: ANU/IBM имеют разные секреты.
        Партия каждого провайдера расходуется только при совпадении его
        собственного fingerprint (или NULL для LfDR/легаси)."""
        if self._store is None:
            return {}
        out: dict[str, int] = {}
        for pid in PROVIDER_IDS:
            try:
                reserve = await self._store.provider_reserve(
                    config_fingerprint=self._provider_fingerprint(pid))
            except Exception:
                logger.warning("[random_source] provider reserve read failed "
                               "| provider=%s", pid, exc_info=True)
                reserve = {}
            count = int(reserve.get(pid, 0) or 0)
            if count > 0:
                out[pid] = count
        return out

    async def _reserve_remaining(self) -> int:
        if self._store is None:
            return 0
        try:
            return await self._store.reserve_remaining(
                config_fingerprint=self._current_fingerprint())
        except Exception:
            logger.warning("[random_source] reserve read failed", exc_info=True)
            return 0

    async def provider_reserve(self) -> dict:
        """Остаток по провайдерам ТОЛЬКО для действующей конфигурации (F4).

        Read-only; канонические id. Партии старой конфигурации сюда не входят
        (они — `provider_stock - provider_reserve` = quarantined)."""
        return await self._provider_reserve_map()

    async def provider_stock(self) -> dict:
        """Весь физический остаток по провайдерам (для quarantine в статусе)."""
        if self._store is None:
            return {}
        try:
            return await self._store.provider_reserve()
        except Exception:
            logger.warning("[random_source] provider stock read failed",
                           exc_info=True)
            return {}

    async def _provider_blocker(self) -> str:
        state = await self._read_state()
        if state and state.get("last_fallback_reason"):
            return str(state["last_fallback_reason"])
        if not self._resolve_key():
            return "provider_unconfigured"
        if state is None or not state.get("activated_at") \
                or state.get("key_fingerprint") != \
                key_fingerprint(self._resolve_key()):
            return "provider_unavailable"
        return "provider_unavailable"

    async def _read_state(self) -> dict | None:
        if self._store is None:
            return None
        try:
            return await self._store.get_state()
        except Exception:
            return None

    # ── draw-API (async; 10b/09 — потребители) ─────────────────────────────
    async def draw_index(self, n: int, *, chat_id=None, purpose: str = "",
                         policy_version: str | None = None,
                         candidates=None, probability: float | None = None
                         ) -> DrawResult:
        """Равномерный индекс 0..n-1 (rejection sampling; n=1 — без расхода).

        `candidates` — опциональные ID пула (только для журнала; cap 50);
        `probability` — порог политики (только для журнала, T-4969).
        Каждый draw — отдельное значение; повторное использование запрещено."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 0
        selected = await self.selected_mode(chat_id)
        pv = str(policy_version or POLICY_VERSION)
        if n <= 0:
            return DrawResult(index=None, deferred=True,
                              reason="validation_failed",
                              selected_source=selected, policy_version=pv)
        if n == 1:
            return DrawResult(index=0, value=None, source=selected,
                              selected_source=selected, policy_version=pv,
                              reason=(None if mca_gates.random_source_enabled()
                                      else "disabled"))
        if not mca_gates.random_source_enabled():
            return DrawResult(index=None, deferred=True, reason="disabled",
                              selected_source=selected, policy_version=pv)
        selection = await self.resolve_selection(chat_id)
        blocker = selection.blocker
        if selection.mode == MODE_QUANTUM:
            result = await self._quantum_index_draw(
                n, selection=selection, chat_id=chat_id, purpose=purpose,
                policy_version=pv, candidates=candidates,
                probability=probability)
            if result is not None:
                self._note_quantum_success()
                return result
            blocker = await self._resolution_blocker(
                selection.resolved_primary)
        fallback = await self.fallback_enabled(chat_id)
        if blocker is None or fallback:
            if blocker is not None:
                self._note_transition(key=f"prng:{blocker}", reason=blocker)
                await self._mark_fallback(blocker,
                                          provider=selection.resolved_primary)
            return await self._prng_index_draw(
                n, chat_id=chat_id, purpose=purpose, policy_version=pv,
                fallback_reason=blocker, candidates=candidates,
                probability=probability)
        self._note_transition(key=f"defer:{blocker}", reason=blocker,
                              deferred=True)
        return DrawResult(index=None, deferred=True, reason=blocker,
                          source=MODE_PSEUDORANDOM, selected_source=selected,
                          fallback_reason=blocker, policy_version=pv)

    async def draw_probability(self, *, chat_id=None, purpose: str = "",
                               policy_version: str | None = None,
                               probability: float | None = None) -> DrawResult:
        """Равномерная величина [0,1) (отдельное значение на каждую проверку).

        `probability` — порог политики (только для журнала, T-4969)."""
        selected = await self.selected_mode(chat_id)
        pv = str(policy_version or POLICY_VERSION)
        if not mca_gates.random_source_enabled():
            return DrawResult(value=None, deferred=True, reason="disabled",
                              selected_source=selected, policy_version=pv)
        selection = await self.resolve_selection(chat_id)
        blocker = selection.blocker
        if selection.mode == MODE_QUANTUM:
            result = await self._quantum_probability_draw(
                selection=selection, chat_id=chat_id, purpose=purpose,
                policy_version=pv, probability=probability)
            if result is not None:
                self._note_quantum_success()
                return result
            blocker = await self._resolution_blocker(
                selection.resolved_primary)
        fallback = await self.fallback_enabled(chat_id)
        if blocker is None or fallback:
            if blocker is not None:
                self._note_transition(key=f"prng:{blocker}", reason=blocker)
                await self._mark_fallback(blocker,
                                          provider=selection.resolved_primary)
            return await self._prng_probability_draw(
                chat_id=chat_id, purpose=purpose, policy_version=pv,
                fallback_reason=blocker, probability=probability)
        self._note_transition(key=f"defer:{blocker}", reason=blocker,
                              deferred=True)
        return DrawResult(value=None, deferred=True, reason=blocker,
                          source=MODE_PSEUDORANDOM, selected_source=selected,
                          fallback_reason=blocker, policy_version=pv)

    async def choose(self, primary, alternatives, *, probability: float | None
                     = None, chat_id=None, purpose: str,
                     policy_version: str | None = None,
                     measurement: str | None = None) -> PolicyChoice:
        return await self._policy.choose(
            primary, alternatives, probability=probability, chat_id=chat_id,
            purpose=purpose, policy_version=policy_version,
            measurement=measurement)

    # ── внутренние draw-пути ───────────────────────────────────────────────
    def _meta(self, *, chat_id, purpose, policy_version, probability=None,
              pool_size=None, candidates=None,
              fallback_reason=None) -> dict:
        return {
            "chat_id": int(chat_id) if chat_id is not None else None,
            "purpose": str(purpose or "")[:120],
            "policy_version": str(policy_version or POLICY_VERSION)[:120],
            "probability": probability,
            "pool_size": pool_size,
            "candidates_json": (
                json.dumps(list(candidates)[:CANDIDATES_CAP],
                           ensure_ascii=False)
                if candidates else None),
            "fallback_reason": fallback_reason,
            "config_version": APP_VERSION,
        }

    async def _quantum_index_draw(self, n: int, *, selection, chat_id, purpose,
                                  policy_version, candidates=None,
                                  probability=None) -> DrawResult | None:
        if self._store is None:
            return None
        pool_candidates = (list(candidates)[:CANDIDATES_CAP]
                           if candidates is not None
                           else list(range(min(n, CANDIDATES_CAP))))
        meta = self._meta(chat_id=chat_id, purpose=purpose,
                          policy_version=policy_version, pool_size=n,
                          candidates=pool_candidates, probability=probability)
        attempts = 0
        for pid in selection.effective_order:
            provider_ids = PROVIDER_STORAGE_IDS.get(pid)
            if provider_ids is None:
                continue
            fingerprint = self._provider_fingerprint(pid)
            for _ in range(MAX_DRAW_ATTEMPTS):
                reserved = await self._store.reserve_draw(
                    n=n, meta=meta, config_fingerprint=fingerprint,
                    provider_ids=provider_ids)
                if reserved is None:
                    break          # у этого провайдера запаса нет/кончился
                attempts += 1
                if reserved.index is not None:
                    return DrawResult(
                        index=int(reserved.index), value=int(reserved.value),
                        source=MODE_QUANTUM, selected_source=MODE_QUANTUM,
                        provider=reserved.provider,
                        provider_id=reserved.provider_id or None,
                        entropy_class=entropy_class_for(reserved.provider_id),
                        batch_id=reserved.batch_id, draw_id=reserved.draw_id,
                        source_impl=source_impl_for(reserved.provider_id),
                        policy_version=str(policy_version or POLICY_VERSION),
                        attempts=attempts)
        return None

    async def _quantum_probability_draw(self, *, selection, chat_id, purpose,
                                        policy_version,
                                        probability=None) -> DrawResult | None:
        if self._store is None:
            return None
        meta = self._meta(chat_id=chat_id, purpose=purpose,
                          policy_version=policy_version,
                          probability=probability)
        for pid in selection.effective_order:
            provider_ids = PROVIDER_STORAGE_IDS.get(pid)
            if provider_ids is None:
                continue
            reserved = await self._store.reserve_draw(
                n=None, meta=meta,
                config_fingerprint=self._provider_fingerprint(pid),
                provider_ids=provider_ids)
            if reserved is None:
                continue
            return DrawResult(value=float(reserved.value) / float(
                reserved.value_range or 1), source=MODE_QUANTUM,
                selected_source=MODE_QUANTUM, provider=reserved.provider,
                provider_id=reserved.provider_id or None,
                entropy_class=entropy_class_for(reserved.provider_id),
                batch_id=reserved.batch_id, draw_id=reserved.draw_id,
                source_impl=source_impl_for(reserved.provider_id),
                policy_version=str(policy_version or POLICY_VERSION))
        return None

    async def _prng_index_draw(self, n: int, *, chat_id, purpose,
                               policy_version,
                               fallback_reason=None,
                               candidates=None, probability=None) -> DrawResult:
        rng = random.Random()          # auto-seed; версия фиксируется ниже
        index = int(rng.randrange(n))
        pool_candidates = (list(candidates)[:CANDIDATES_CAP]
                           if candidates is not None
                           else list(range(min(n, CANDIDATES_CAP))))
        draw_id = await self._journal_prng(
            chat_id=chat_id, purpose=purpose, policy_version=policy_version,
            value=index, selected_id=str(index), pool_size=n,
            candidates=pool_candidates, probability=probability,
            fallback_reason=fallback_reason)
        return DrawResult(index=index, value=index, source=MODE_PSEUDORANDOM,
                          selected_source=await self.selected_mode(chat_id),
                          provider=PROVIDER_PRNG, draw_id=draw_id,
                          source_impl=SOURCE_IMPL_PRNG,
                          fallback_reason=fallback_reason,
                          policy_version=str(policy_version or POLICY_VERSION))

    async def _prng_probability_draw(self, *, chat_id, purpose,
                                     policy_version,
                                     fallback_reason=None,
                                     probability=None) -> DrawResult:
        rng = random.Random()
        value = float(rng.random())
        draw_id = await self._journal_prng(
            chat_id=chat_id, purpose=purpose, policy_version=policy_version,
            value=value, selected_id=None, pool_size=None, candidates=None,
            probability=probability, fallback_reason=fallback_reason)
        return DrawResult(value=value, source=MODE_PSEUDORANDOM,
                          selected_source=await self.selected_mode(chat_id),
                          provider=PROVIDER_PRNG, draw_id=draw_id,
                          source_impl=SOURCE_IMPL_PRNG,
                          fallback_reason=fallback_reason,
                          policy_version=str(policy_version or POLICY_VERSION))

    async def _journal_prng(self, *, chat_id, purpose, policy_version, value,
                            selected_id, pool_size, candidates,
                            fallback_reason, probability=None) -> str | None:
        if self._store is None:
            return None
        draw_id = uuid.uuid4().hex
        record = {
            "draw_id": draw_id,
            "created_at": int(time.time()),
            "chat_id": int(chat_id) if chat_id is not None else None,
            "purpose": str(purpose or "")[:120],
            "source": MODE_PSEUDORANDOM,
            "provider": PROVIDER_PRNG,
            "batch_id": None,
            "value": float(value),
            "candidates_json": (
                json.dumps(list(candidates)[:CANDIDATES_CAP],
                           ensure_ascii=False) if candidates else None),
            "pool_size": pool_size,
            "probability": probability,
            "policy_version": str(policy_version or POLICY_VERSION)[:120],
            "selected_id": selected_id,
            "fallback_reason": fallback_reason,
            "config_version": APP_VERSION,
        }
        try:
            await self._store.journal_draw(record)
        except Exception:
            logger.warning("[random_source] prng journal failed",
                           exc_info=True)
            return None
        return draw_id

    async def _mark_fallback(self, reason: str, *,
                             provider: str | None = None) -> None:
        """Зафиксировать причину отката.

        `mca_random_state` — ANU-scoped (G16): писать в него причину ЧУЖОГО
        провайдера нельзя (иначе `anu_state()` показывал бы деградацию ANU из-за
        LfDR). Для LfDR причина живёт в in-memory health и событиях."""
        if self._store is None:
            return
        if provider not in (None, PROVIDER_ID_ANU):
            return
        try:
            await self._store.write_state(last_fallback_reason=str(reason)[:160],
                                          last_fallback_at=int(time.time()))
        except Exception:
            logger.warning("[random_source] fallback state write failed",
                           exc_info=True)

    # ── ANU/LfDR: fetch/активация/refill/квота ─────────────────────────────
    async def _fetch_batch(self, key: str, *, manual: bool,
                           provider: str = PROVIDER_ID_ANU,
                           deposit=None) -> AnuBatch:
        """Один запрос к выбранному провайдеру (P3: ANU + LfDR; P5: IBM).

        ANU — существующий клиент/контракт (ключ, endpoint, data_type).
        LfDR — общий сервисный `LfdrClient` (N1: breaker/min-interval одни и
        те же между refill/проверками), публичный вход без ключа, uint8.
        IBM — общий `IbmQuantumRuntimeClient`: реальный QPU Sampler,
        read-only проверки отдельно, durable job в существующих `task_jobs`."""
        if provider == PROVIDER_ID_LFDR:
            started = time.monotonic()
            batch = await lfdr_fetch(client=self._get_lfdr_client(),
                                     length=self._batch_length())
            batch.latency_ms = int((time.monotonic() - started) * 1000)
            self._last_latency_ms = batch.latency_ms
            return batch
        if provider == PROVIDER_ID_IBM:
            from services.task_supervisor import TaskJobStore
            started = time.monotonic()
            batch = await self._get_ibm_client().fetch(
                api_key=self._ibm_api_key(), crn=self._ibm_crn(),
                instance=self._ibm_instance(), region=self._ibm_region(),
                channel=self._ibm_channel(), length=self._batch_length(),
                job_store=(TaskJobStore(self.db)
                           if self.db is not None else None),
                deposit=deposit,
                account_key=self._ibm_account_key(),
                config_fp=self._ibm_config_fingerprint())
            batch.latency_ms = int((time.monotonic() - started) * 1000)
            self._last_latency_ms = batch.latency_ms
            return batch
        if provider != PROVIDER_ID_ANU:
            raise AnuError("provider_unconfigured",
                           "adapter not implemented", sent=False)
        data_type = self._data_type()
        size = (mca_gates.random_quantum_hex_block_size()
                if data_type in HEX_TYPES else None)
        client = self._get_client()
        started = time.monotonic()
        batch = await client.fetch(
            key=key, length=self._batch_length(), data_type=data_type,
            endpoint=self._endpoint(), size=size)
        batch.latency_ms = int((time.monotonic() - started) * 1000)
        self._last_latency_ms = batch.latency_ms
        return batch

    async def _record_quota_result(self, outcome: str, *,
                                   manual: bool, reason: str | None = None
                                   ) -> None:
        if self._store is None:
            return
        try:
            await self._store.quota_record(
                account_key=self._account_key(), period=_utc_period(),
                outcome=outcome, manual=manual, reason=reason)
        except Exception:
            logger.warning("[random_source] quota write failed", exc_info=True)

    async def _record_quota_error(self, exc: AnuError, *, manual: bool
                                  ) -> None:
        if not exc.sent:
            return                 # запрос не ушёл — квота не расходовалась
        outcome = "unknown" if exc.code == "timeout" else "failed"
        await self._record_quota_result(outcome, manual=manual,
                                        reason=exc.code)

    async def _confirm_activation(self, batch_id: str) -> bool:
        """Внутренний self-check через адаптер (один draw purpose
        `activation_selfcheck`, без отправки сообщения в чат) + active.

        F-01: расходуется ТОЛЬКО зачисленная партия `batch_id`. Если в ней
        нет расходуемого значения — честный отказ; более старая LfDR/NULL-
        партия не подменяет self-check, а `activation_batch_id` в state
        всегда называет партию фактически израсходованного значения."""
        if self._store is None:
            return False
        chunk = await self._store.reserve_chunk(
            1, config_fingerprint=self._current_fingerprint(),
            batch_id=str(batch_id))
        if not chunk:
            return False
        item = chunk[0]
        if str(item.batch_id) != str(batch_id):
            # Защита контракта: store обязан вернуть только запрошенную
            # партию; чужое значение не должно подтверждать активацию.
            return False
        adapter = CoreDreamRandomSource(
            pipeline_run_id=None, chat_id=0, source=MODE_QUANTUM,
            provider=item.provider, batch_id=item.batch_id,
            data_type=item.data_type, values=[item.value],
            draw_ids=[item.draw_id], journal_sink=self._enqueue_journal)
        items, _meta = adapter.pick(
            ["activation_selfcheck_a", "activation_selfcheck_b"],
            chat_id=0, purpose=PURPOSE_ACTIVATION_SELFCHECK, k=1)
        await self.flush_journal()
        if not items:
            return False
        key = self._resolve_key()
        await self._store.write_state(
            key_fingerprint=key_fingerprint(key),
            activation_batch_id=str(batch_id), activated_at=int(time.time()),
            last_fallback_reason=None, last_fallback_at=None)
        self._note_quantum_success()
        self._emit("random_activation", outcome=mca_events.OUTCOME_SUCCESS,
                   reason_code="quantum_activated", stage="activate",
                   provider=PROVIDER_ID_ANU,
                   entity_ids={"batch_id": str(batch_id)},
                   duration_ms=self._last_latency_ms)
        return True

    async def sync_batch_provenance(self) -> int:
        """Backfill `config_fingerprint` легаси-партий (arch P1 D2).

        Привязка выполняется ТОЛЬКО когда durable state подтверждает тот же
        ключ (`activated_at` + совпадающий `key_fingerprint`) и только для
        NULL-партий ANU; иначе партии остаются NULL (= совместимы и
        расходуются как раньше). Идемпотентно; исторические значения/строки
        не переписываются."""
        if self._store is None:
            return 0
        key = self._resolve_key()
        fingerprint = key_fingerprint(key) if key else ""
        if not fingerprint:
            return 0
        state = await self._read_state()
        if (not state or not state.get("activated_at")
                or state.get("key_fingerprint") != fingerprint):
            return 0
        try:
            return await self._store.backfill_config_fingerprint(
                fingerprint, provider_ids=ANU_PROVIDER_IDS)
        except Exception:
            logger.warning("[random_source] provenance backfill failed",
                           exc_info=True)
            return 0

    async def activate(self, *, manual: bool = True) -> dict:
        """Проверка соединения с ключом → валидная партия → зачисление →
        self-check → `quantum_activated` → effective quantum. HTTP 200 без
        проверки содержимого, mock и fallback активацией НЕ являются.

        Зачисленная партия помечается `config_fingerprint` действующего
        ключа (arch P1 D3): после смены ключа A→B партии A не расходуются."""
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return {"state": ANU_STATE_DISABLED, "activated": False,
                    "deposited": False,
                    "blocker": None, "key_present": False}
        if self._store is None:
            return {"state": ANU_STATE_DEGRADED, "activated": False,
                    "deposited": False,
                    "blocker": "provider_unavailable", "key_present": False}
        key = self._resolve_key()
        if not key:
            await self._mark_state_failure("provider_unconfigured")
            self._emit("random_activation", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN,
                       reason_code="provider_unconfigured", stage="activate")
            return {"state": ANU_STATE_UNCONFIGURED, "activated": False,
                    "deposited": False,
                    "blocker": "provider_unconfigured", "key_present": False}
        fingerprint = key_fingerprint(key)
        state = await self._read_state()
        if (state and state.get("key_fingerprint")
                and state.get("key_fingerprint") != fingerprint):
            # смена ключа → unverified до успешной проверки (не healthy)
            if self._store is not None:
                await self._store.write_state(
                    key_fingerprint=fingerprint, activation_batch_id=None,
                    activated_at=None, last_fallback_reason=None,
                    last_fallback_at=None)
        try:
            batch = await self._fetch_batch(key, manual=manual)
        except AnuError as exc:
            await self._record_quota_error(exc, manual=manual)
            await self._mark_state_failure(exc.code, fingerprint=fingerprint)
            self._emit("random_activation", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN, reason_code=exc.code,
                       stage="activate", provider=PROVIDER_ID_ANU,
                       error_json={"type": "AnuError", "code": exc.code,
                                   "retryable": exc.retryable,
                                   "sent": exc.sent})
            return {"state": await self.anu_state(), "activated": False,
                    "deposited": False,
                    "blocker": exc.code, "reason": exc.reason,
                    "key_present": True}
        await self._record_quota_result("success", manual=manual)
        batch_id = await self._store.insert_batch(
            batch, config_fingerprint=fingerprint)
        activated = await self._confirm_activation(batch_id)
        if not activated:
            self._emit("random_activation", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN,
                       reason_code="validation_failed", stage="activate",
                       provider=PROVIDER_ID_ANU)
            return {"state": await self.anu_state(), "activated": False,
                    "deposited": False,
                    "blocker": "validation_failed", "key_present": True}
        await self.sync_batch_provenance()
        return {"state": ANU_STATE_ACTIVE, "activated": True,
                "deposited": True, "config_fingerprint": fingerprint,
                "blocker": None, "key_present": True, "batch_id": batch_id,
                "length": len(batch.values), "latency_ms": batch.latency_ms}

    async def _mark_state_failure(self, reason: str, *,
                                  fingerprint: str | None = None) -> None:
        if self._store is None:
            return
        fields: dict[str, Any] = {
            "last_fallback_reason": str(reason)[:160],
            "last_fallback_at": int(time.time()),
        }
        if fingerprint:
            fields["key_fingerprint"] = fingerprint
        try:
            await self._store.write_state(**fields)
        except Exception:
            logger.warning("[random_source] state write failed", exc_info=True)

    @staticmethod
    def _check_retry_after(age: float, cooldown: float) -> int:
        """Целые секунды до следующей ручной проверки (≥1 при активном cooldown)."""
        remaining = float(cooldown) - float(age)
        return max(1, int(remaining + 0.999)) if remaining > 0 else 0

    def _prune_checks(self, now: float, cooldown: float) -> None:
        ttl = max(float(cooldown), 60.0) * 4
        stale = [fp for fp, (ts, _res) in self._recent_checks.items()
                 if now - ts > ttl]
        for fp in stale:
            self._recent_checks.pop(fp, None)
        while len(self._recent_checks) > 64:
            oldest = min(self._recent_checks.items(), key=lambda kv: kv[1][0])
            self._recent_checks.pop(oldest[0], None)

    async def test_connection(self, draft_key: str | None = None, *,
                              manual: bool = True,
                              provider: str = PROVIDER_ID_ANU,
                              draft_crn: str | None = None) -> dict:
        """Backend-проверка подключения (кнопка — блок C): status/latency/
        дата/размер партии/очищенная ошибка. Draft-ключ (POST body) не
        сохраняется и не логируется; значения ЧЕРНОВОЙ проверки в рабочий
        запас НЕ зачисляются (`deposited=false`); зачисление — только для
        сохранённого ключа через `activate()` (с `config_fingerprint`).
        Неизвестный ключ не показывается healthy до успешной проверки.

        Singleflight (T-4977): повторные клики с тем же ключом, пока проверка
        в полёте, получают ОДИН общий результат (один запрос к провайдеру);
        клик с изменённым ключом дожидается текущей проверки и запускает
        свою (min interval провайдера не даёт лавины). После завершения —
        cooldown (G14/D14): повторный клик в окне возвращает тот же результат
        с `cooldown=true`/`retry_after_seconds` и НЕ делает нового запроса."""
        if str(provider or "") == PROVIDER_ID_IBM:
            return await self.ibm_check_access(
                draft_key=draft_key, draft_crn=draft_crn)
        key = str(draft_key or "").strip() or self._resolve_key()
        fingerprint = key_fingerprint(key) if key else ""
        now = self._clock()
        cooldown = float(mca_gates.random_manual_check_cooldown_seconds())
        cached = self._recent_checks.get(fingerprint) if fingerprint else None
        if cached is not None and cooldown > 0:
            age = now - cached[0]
            if 0 <= age < cooldown:
                result = dict(cached[1])
                result["cooldown"] = True
                result["retry_after_seconds"] = self._check_retry_after(
                    age, cooldown)
                return result
        async with self._check_lock:
            if (self._check_task is not None
                    and not self._check_task.done()
                    and self._check_key == key):
                task = self._check_task          # coalesce: тот же ключ
            else:
                task = asyncio.create_task(self._run_check(key, manual=manual))
                self._check_task = task
                self._check_key = key
        try:
            result = await task
        except Exception as exc:      # неожиданный сбой — честный ответ, не 500
            logger.warning("[random_source] check failed | error=%s",
                           type(exc).__name__)
            result = {"healthy": False, "blocker": "provider_unavailable",
                      "key_present": bool(key), "persisted": False,
                      "deposited": False}
        finally:
            if task.done() and self._check_task is task:
                self._check_task = None
        if isinstance(result, dict):
            result = dict(result)
            result.setdefault("deposited", False)
            result.setdefault("cooldown", False)
            result["retry_after_seconds"] = 0
            if fingerprint and cooldown > 0:
                self._recent_checks[fingerprint] = (self._clock(), dict(result))
                self._prune_checks(self._clock(), cooldown)
        return result

    async def _run_check(self, key: str, *, manual: bool) -> dict:
        """Одна фактическая проверка (ключ уже разрешён вызывающим).

        Черновой ключ (`key != stored`) изолирован (arch P1 D3, G3): запрос
        провайдера выполняется, квота учитывается, но партия НЕ пишется в
        рабочий `mca_random_batches` — `deposited=false`, второй store нет."""
        if not key:
            return {"healthy": False, "blocker": "provider_unconfigured",
                    "key_present": False, "persisted": False,
                    "deposited": False}
        stored = self._resolve_key()
        if stored and key == stored:
            result = await self.activate(manual=manual)
            return {"healthy": bool(result.get("activated")),
                    "blocker": result.get("blocker"),
                    "reason": result.get("reason"),
                    "key_present": True, "persisted": True,
                    "deposited": bool(result.get("deposited")),
                    "config_fingerprint": result.get("config_fingerprint"),
                    "state": result.get("state"),
                    "length": result.get("length"),
                    "latency_ms": result.get("latency_ms"),
                    "checked_at": int(time.time())}
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return {"healthy": False, "blocker": "disabled",
                    "key_present": bool(key), "persisted": False,
                    "deposited": False}
        try:
            batch = await self._fetch_batch(key, manual=manual)
        except AnuError as exc:
            await self._record_quota_error(exc, manual=manual)
            return {"healthy": False, "blocker": exc.code,
                    "reason": exc.reason, "key_present": True,
                    "persisted": False, "deposited": False}
        await self._record_quota_result("success", manual=manual)
        # Черновой ключ: квота уже израсходована провайдером, но в рабочий
        # запас не зачисляем (проверка ≠ активация чужой конфигурации).
        return {"healthy": True, "blocker": None, "key_present": True,
                "persisted": False, "deposited": False,
                "length": len(batch.values),
                "latency_ms": batch.latency_ms,
                "checked_at": int(time.time())}

    async def ibm_check_access(self, *, draft_key: str | None = None,
                               draft_crn: str | None = None) -> dict:
        """Read-only «Проверить доступ» IBM: без Sampler и без job."""
        key = str(draft_key or "").strip() or self._ibm_api_key()
        crn = str(draft_crn or "").strip() or self._ibm_crn()
        client = self._ibm_client if self._ibm_client_pinned else \
            IbmQuantumRuntimeClient()
        result = await client.check_access(
            api_key=key, crn=crn, instance=self._ibm_instance(),
            region=self._ibm_region(), channel=self._ibm_channel())
        persisted = bool(
            key and key == self._ibm_api_key()
            and (not draft_crn or crn == self._ibm_crn()))
        result.setdefault("persisted", persisted)
        result.setdefault("deposited", False)
        if persisted:
            if result.get("healthy"):
                self._note_ibm_success(
                    job={"backend": result.get("selected_backend"),
                         "state": "access_checked"},
                    plan=result.get("plan"), usage=result.get("usage"))
            else:
                self._note_ibm_failure(str(result.get("blocker")
                                            or "provider_unavailable"),
                                       stage=result.get("stage"))
        return result

    async def ibm_hardware_smoke(self, *, draft_key: str | None = None,
                                 draft_crn: str | None = None,
                                 shots: int = IBM_SMOKE_SHOTS) -> dict:
        """Отдельное «Проверить получение измерений» IBM (ограниченный QPU job).

        Использует ТОТ ЖЕ durable `task_jobs`/`TaskSupervisor`, дневные лимиты
        job/QPU, max_inflight и cooldown/singleflight, что и refill. Партия НЕ
        зачисляется в рабочий запас побочным эффектом."""
        key = str(draft_key or "").strip() or self._ibm_api_key()
        crn = str(draft_crn or "").strip() or self._ibm_crn()
        crn_present = bool(crn)
        fingerprint = key_fingerprint("|".join((
            key, crn, self._ibm_instance(), self._ibm_region(),
            self._ibm_channel())))
        now = self._clock()
        cooldown = float(mca_gates.random_manual_check_cooldown_seconds())
        cached = self._ibm_smoke_recent.get(fingerprint)
        if cached is not None and cooldown > 0:
            age = now - cached[0]
            if 0 <= age < cooldown:
                result = dict(cached[1])
                result["cooldown"] = True
                result["retry_after_seconds"] = self._check_retry_after(
                    age, cooldown)
                return result
        async with self._ibm_smoke_lock:
            if (self._ibm_smoke_task is not None
                    and not self._ibm_smoke_task.done()
                    and self._ibm_smoke_key == fingerprint):
                task = self._ibm_smoke_task
            else:
                task = asyncio.create_task(
                    self._run_ibm_smoke(
                        key=key, crn=crn, crn_present=crn_present,
                        shots=shots))
                self._ibm_smoke_task = task
                self._ibm_smoke_key = fingerprint
        try:
            result = await task
        except Exception as exc:
            logger.warning("[random_source] ibm smoke failed | error=%s",
                           type(exc).__name__)
            result = _ibm_error_result(
                code="provider_unavailable", stage="request",
                reason=_clean_error_text(str(exc), key),
                key_present=bool(key), crn_present=crn_present,
                instance=self._ibm_instance(), region=self._ibm_region(),
                channel=self._ibm_channel(), checked_at=int(time.time()))
        finally:
            if task.done() and self._ibm_smoke_task is task:
                self._ibm_smoke_task = None
        result = dict(result)
        result.setdefault("deposited", False)
        result.setdefault("cooldown", False)
        result["retry_after_seconds"] = 0
        if fingerprint and cooldown > 0 and result.get("blocker") is None:
            self._ibm_smoke_recent[fingerprint] = (
                self._clock(), dict(result))
        return result

    async def _run_ibm_smoke(self, *, key: str, crn: str,
                             crn_present: bool, shots: int) -> dict:
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return _ibm_error_result(
                code="disabled", stage="disabled", reason="disabled",
                key_present=bool(key), crn_present=crn_present,
                instance=self._ibm_instance(), region=self._ibm_region(),
                channel=self._ibm_channel())
        if not key:
            return _ibm_error_result(
                code="provider_unconfigured", stage="key",
                reason="no api key", key_present=False,
                crn_present=crn_present, instance=self._ibm_instance(),
                region=self._ibm_region(), channel=self._ibm_channel())
        blocker = await self._ibm_skip_reason()
        if blocker in {"daily_job_limit", "daily_usage_limit",
                       "job_in_progress", "dependency_missing",
                       "circuit_open", "auth_failed", "permission_denied",
                       "invalid_instance", "invalid_channel",
                       "invalid_region"}:
            return _ibm_error_result(
                code=blocker, stage=_ibm_stage_for_code(blocker),
                reason="ibm smoke blocked by limit/health",
                key_present=True, crn_present=crn_present,
                instance=self._ibm_instance(), region=self._ibm_region(),
                channel=self._ibm_channel())
        client = self._ibm_client if self._ibm_client_pinned else \
            IbmQuantumRuntimeClient()
        from services.task_supervisor import (TaskJobStore,
                                              get_task_supervisor)
        job_store = TaskJobStore(self.db) if self.db is not None else None
        result = await client.hardware_smoke(
            api_key=key, crn=crn, instance=self._ibm_instance(),
            region=self._ibm_region(), channel=self._ibm_channel(),
            shots=shots, job_store=job_store,
            supervisor=(get_task_supervisor()
                        if job_store is not None else None),
            account_key=self._ibm_account_key(),
            config_fp=self._ibm_config_fingerprint())
        persisted = bool(
            key and key == self._ibm_api_key()
            and (not crn or crn == self._ibm_crn()))
        result.setdefault("persisted", persisted)
        result["deposited"] = False
        if persisted:
            if result.get("healthy"):
                self._note_ibm_success(
                    job={"job_id": result.get("job_id"),
                         "backend": result.get("backend"),
                         "state": IBM_JOB_COMPLETED},
                    plan=result.get("plan"),
                    usage=({"usage_seconds": result.get("usage_seconds")}
                           if result.get("usage_seconds") is not None
                           else None))
            else:
                self._note_ibm_failure(
                    str(result.get("blocker") or "provider_unavailable"),
                    stage=result.get("stage"))
        return result

    def _provider_can_fetch(self, provider_id: str) -> bool:
        """Может ли контур сделать запрос этому провайдеру (адаптер + конфиг)."""
        if provider_id == PROVIDER_ID_ANU:
            return bool(self._resolve_key())
        if provider_id == PROVIDER_ID_LFDR:
            return True         # публичный, ключа нет; адаптер P2
        if provider_id == PROVIDER_ID_IBM:
            return (self._ibm_configured()
                    and self._ibm_dependency_available())
        return False

    async def _provider_skip_reason(self, provider_id: str) -> str | None:
        """Почему провайдера не стоит пытать в ЭТОМ проходе refill.

        Без сети и без записи: открытый breaker/backoff клиента; постоянные
        причины ANU (неверный ключ `auth_failed`, исчерпанная месячная квота).
        Транзиентные 5xx/timeout не кэшируются навсегда — их ограничивает
        breaker, а в текущем вызове провайдер повторно не пробуется."""
        if provider_id == PROVIDER_ID_ANU:
            try:
                if not self._get_client().available():
                    return "circuit_open"
            except Exception:      # pragma: no cover — fail-open
                pass
            state = await self._read_state() or {}
            reason = str(state.get("last_fallback_reason") or "")
            if reason in ANU_STATE_PERSISTENT_BLOCKERS:
                return reason
            return None
        if provider_id == PROVIDER_ID_LFDR:
            client = self._lfdr_client
            if client is not None and not client.available():
                return "circuit_open"
            return None
        if provider_id == PROVIDER_ID_IBM:
            return await self._ibm_skip_reason()
        return "no_adapter"

    async def _ibm_skip_reason(self) -> str | None:
        """Почему IBM не стоит пытать в этом проходе (без сети/без job)."""
        if not self._ibm_dependency_available():
            return "dependency_missing"
        current_fp = self._ibm_config_fingerprint()
        persistent = str(self._ibm_health.get("last_error") or "")
        if (persistent in {"auth_failed", "permission_denied",
                           "invalid_instance", "invalid_channel",
                           "invalid_region"}
                and str(self._ibm_health.get("config_fp") or "") == current_fp):
            # Ошибка конфигурации не лечится повтором; после смены key/CRN
            # fingerprint меняется и блокер снимается сам.
            return persistent
        client = self._ibm_client
        if client is not None and not client.available():
            return "circuit_open"
        active = await self._ibm_active_jobs()
        if any(str(r.get("status") or "") == "interrupted"
               for r in active):
            # Строка снята watchdog'ом — пробуем attach по сохранённому job ID
            # (без resubmit) и в этом проходе новых заданий не создаём.
            try:
                await self._recover_ibm_jobs()
            except Exception:
                logger.warning("[random_source] ibm recovery kick failed",
                               exc_info=True)
        if len(active) >= self._ibm_max_inflight():
            return "job_in_progress"
        if await self._ibm_jobs_today() >= self._ibm_max_jobs_per_day():
            return "daily_job_limit"
        if await self._ibm_usage_today() >= \
                self._ibm_max_qpu_seconds_per_day():
            return "daily_usage_limit"
        return None

    async def _refill_plan(self) -> tuple[list[str], list[dict]]:
        """Bounded-план refill: очередь попыток + пропущенные по health.

        Один проход по действующему порядку (≤ числа провайдеров), каждый
        провайдер — не более одной попытки за вызов."""
        selection = await self.resolve_selection(None)
        queue: list[str] = []
        skipped: list[dict] = []
        for pid in selection.effective_order:
            if not self._provider_can_fetch(pid):
                continue
            reason = await self._provider_skip_reason(pid)
            if reason:
                skipped.append({"provider": pid, "status": "skipped",
                                "reason": reason})
            else:
                queue.append(pid)
        return queue, skipped

    async def _refill_target(self) -> str | None:
        """Первый запрашиваемый провайдер действующего порядка (D5).

        Цель startup: первый провайдер, у которого есть всё для запроса и
        health не запрещает попытку (breaker/постоянный блокер исключены)."""
        queue, _skipped = await self._refill_plan()
        return queue[0] if queue else None

    async def refill_if_needed(self, *, force: bool = False) -> dict:
        """Фоновое пополнение партиями (не запрос на каждый draw).

        Singleflight через `TaskSupervisor.run(owner="random.source",
        kind="refill", coalesce_key="random.refill:<account>:<provider>")` +
        durable `task_jobs`; watermark/buffer_max bounded; K3 OFF → не
        запускается.

        QRNG P3 (F2): провайдеры действующего порядка пробуются
        ПОСЛЕДОВАТЕЛЬНО, один проход, каждый не более одного раза. Провайдер
        с открытым breaker/постоянным блокером пропускается; при неудачном
        fetch (auth/rate/5xx/timeout) — следующий. `completed` возвращается
        только при реально зачисленной партии; полностью провалившийся проход
        — честный `failed` с причиной и списком попыток."""
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return {"status": "disabled"}
        if not mca_gates.random_refill_enabled() and not force:
            return {"status": "disabled", "reason": "refill_disabled"}
        queue, attempts = await self._refill_plan()
        if not queue:
            if self._ibm_configured() and \
                    not self._ibm_dependency_available():
                return {"status": "blocked",
                        "reason": "dependency_missing",
                        "attempts": attempts}
            if not self._resolve_key() and not attempts:
                await self._mark_state_failure("provider_unconfigured")
                return {"status": "blocked", "reason": "provider_unconfigured",
                        "attempts": attempts}
            last = attempts[-1]["reason"] if attempts else "provider_unavailable"
            return {"status": "blocked", "reason": last,
                    "attempts": attempts}
        if self._store is None or self.db is None:
            return {"status": "blocked", "reason": "provider_unavailable"}
        buffer_max = self._buffer_max()
        # Пол партии: при buffer_max < batch_length одна партия всё же
        # помещается (иначе запас нечем заполнить); bound = max(...).
        limit_max = max(buffer_max, self._batch_length())
        from services.task_supervisor import (QueueFullError, TaskJobStore,
                                              get_task_supervisor)
        supervisor = get_task_supervisor()
        job_store = TaskJobStore(self.db)
        reserve = await self._provider_reserve_map()
        for target in queue:
            remaining = int(reserve.get(target, 0) or 0)
            if not force:
                if remaining >= limit_max:
                    return {"status": "skipped", "reason": "buffer_full",
                            "provider": target, "remaining": remaining,
                            "attempts": attempts}
                if remaining >= self._low_watermark():
                    return {"status": "skipped", "reason": "watermark_ok",
                            "provider": target, "remaining": remaining,
                            "attempts": attempts}
                if remaining > 0 and remaining + self._batch_length() > limit_max:
                    return {"status": "skipped", "reason": "buffer_full",
                            "provider": target, "remaining": remaining,
                            "attempts": attempts}
            coalesce = f"random.refill:{self._account_key()}:{target}"
            outcome: dict = {}

            async def _job(pid: str = target, box: dict = outcome) -> str:
                box["result"] = await self._do_refill(pid)
                return "ok" if box["result"].get("ok") else "fail"

            try:
                # kind="refill" (D2): TaskSupervisor трактует его как
                # второстепенный класс — при переполнении bounded-очереди job
                # отклоняется с видимой причиной `queue_full` (singleflight
                # coalesce_key защищает от дублей; следующий draw/старт повторит).
                record = await supervisor.run(
                    _job, owner="random.source", kind="refill",
                    coalesce_key=coalesce, job_store=job_store)
            except QueueFullError:
                logger.info("[random_source] refill queue full — deferred | "
                            "account=%s", self._account_key())
                return {"status": "deferred", "reason": "queue_full",
                        "provider": target, "attempts": attempts}
            except Exception as exc:
                logger.warning("[random_source] refill job failed | error=%s",
                               type(exc).__name__, exc_info=True)
                attempts.append({"provider": target, "status": "failed",
                                 "reason": "provider_unavailable"})
                continue
            result = outcome.get("result")
            if result is None:
                # Коалесцировано с уже идущей задачей: исход не наш —
                # completed без доказанной партии не заявляется.
                return {"status": record.status, "job_id": record.job_id,
                        "task_id": record.task_id, "reason": "coalesced",
                        "coalesced": True, "provider": target,
                        "attempts": attempts}
            if result.get("ok"):
                return {"status": record.status, "job_id": record.job_id,
                        "task_id": record.task_id, "reason": None,
                        "provider": target,
                        "batch_id": result.get("batch_id"),
                        "length": result.get("length"),
                        "attempts": attempts}
            attempts.append({"provider": target, "status": "failed",
                             "reason": result.get("reason")})
            self._last_refill_reason = result.get("reason")
        last = attempts[-1] if attempts else {"provider": None,
                                               "reason": "provider_unavailable"}
        return {"status": "failed", "reason": last.get("reason"),
                "provider": last.get("provider"), "attempts": attempts}

    async def _do_refill(self, provider: str) -> dict:
        """Одна партия выбранного провайдера.

        ANU — прежний путь (квота, durable state/активация, fingerprint ключа).
        LfDR — публичный путь: без ключа, без квоты ANU и без записи в
        ANU-scoped `mca_random_state` (G16); партия привязывается как NULL
        (секретной конфигурации у LfDR нет) и сразу расходуема."""
        if provider == PROVIDER_ID_LFDR:
            return await self._do_lfdr_refill()
        if provider == PROVIDER_ID_IBM:
            return await self._do_ibm_refill()
        if provider != PROVIDER_ID_ANU:
            return {"ok": False, "reason": "provider_unconfigured"}
        key = self._resolve_key()
        try:
            batch = await self._fetch_batch(key, manual=False,
                                            provider=PROVIDER_ID_ANU)
        except AnuError as exc:
            await self._record_quota_error(exc, manual=False)
            await self._mark_state_failure(exc.code,
                                           fingerprint=key_fingerprint(key))
            self._last_refill_reason = exc.code
            self._emit("random_batch", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN, reason_code=exc.code,
                       stage="receive", provider=PROVIDER_ID_ANU,
                       error_json={"type": "AnuError", "code": exc.code,
                                   "retryable": exc.retryable,
                                   "sent": exc.sent})
            return {"ok": False, "reason": exc.code}
        await self._record_quota_result("success", manual=False)
        batch_id = await self._store.insert_batch(
            batch, config_fingerprint=key_fingerprint(key))
        self._last_refill_reason = None
        self._emit("random_batch", outcome=mca_events.OUTCOME_SUCCESS,
                   reason_code=None, stage="receive",
                   provider=PROVIDER_ID_ANU,
                   entity_ids={"batch_id": batch_id},
                   duration_ms=batch.latency_ms)
        state = await self._read_state()
        fingerprint = key_fingerprint(key)
        if (state is None or not state.get("activated_at")
                or state.get("key_fingerprint") != fingerprint):
            # первая валидная партия с этим ключом — активация через self-check
            await self._confirm_activation(batch_id)
        else:
            await self._store.write_state(
                last_fallback_reason=None, last_fallback_at=None)
            self._note_quantum_success()
            await self.sync_batch_provenance()
        await self._prune_bounded()
        return {"ok": True, "batch_id": batch_id, "length": len(batch.values)}

    async def _do_lfdr_refill(self) -> dict:
        """LfDR-партия через ОБЩИЙ клиент (N1: breaker/min-interval)."""
        try:
            batch = await self._fetch_batch("", manual=False,
                                            provider=PROVIDER_ID_LFDR)
        except AnuError as exc:
            self._note_lfdr_failure(exc.code)
            self._last_refill_reason = exc.code
            self._emit("random_batch", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN, reason_code=exc.code,
                       stage="receive", provider=PROVIDER_ID_LFDR,
                       error_json={"type": "LfdrError", "code": exc.code,
                                   "retryable": exc.retryable,
                                   "sent": exc.sent})
            return {"ok": False, "reason": exc.code}
        # NULL-fingerprint: у LfDR нет секретной конфигурации, которую нужно
        # изолировать; партия расходуема и не привязана к ANU-ключу.
        batch_id = await self._store.insert_batch(
            batch, config_fingerprint=None)
        self._last_refill_reason = None
        self._note_lfdr_success(latency_ms=batch.latency_ms)
        self._note_quantum_success()
        self._emit("random_batch", outcome=mca_events.OUTCOME_SUCCESS,
                   reason_code=None, stage="receive",
                   provider=PROVIDER_ID_LFDR,
                   entity_ids={"batch_id": batch_id},
                   duration_ms=batch.latency_ms)
        await self._prune_bounded()
        return {"ok": True, "batch_id": batch_id, "length": len(batch.values)}

    async def _do_ibm_refill(self) -> dict:
        """IBM-партия через реальный QPU + durable job lifecycle.

        Зачисление выполняется внутри job-корутины (deposit), поэтому
        `completed` в `task_jobs` означает реально записанную партию; поздний
        результат после рестарта зачисляется recovery-путём без дубля."""
        if not self._ibm_configured():
            return {"ok": False, "reason": "provider_unconfigured"}
        if not self._ibm_dependency_available():
            return {"ok": False, "reason": "dependency_missing"}
        fingerprint = self._ibm_config_fingerprint()

        async def _deposit(batch: AnuBatch) -> str:
            return await self._ibm_deposit_batch(batch, fingerprint)

        try:
            batch = await self._fetch_batch(
                "", manual=False, provider=PROVIDER_ID_IBM,
                deposit=_deposit)
        except AnuError as exc:
            self._note_ibm_failure(exc.code, stage=getattr(exc, "stage", None))
            self._last_refill_reason = exc.code
            self._emit("random_batch", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN, reason_code=exc.code,
                       stage="receive", provider=PROVIDER_ID_IBM,
                       error_json={"type": "IbmError", "code": exc.code,
                                   "retryable": exc.retryable,
                                   "sent": exc.sent,
                                   "stage": getattr(exc, "stage", None)})
            return {"ok": False, "reason": exc.code}
        provenance = dict(batch.provenance or {})
        self._last_refill_reason = None
        self._note_ibm_success(
            latency_ms=batch.latency_ms,
            job={"job_id": provenance.get("job_id"),
                 "backend": provenance.get("backend"),
                 "state": IBM_JOB_COMPLETED},
            plan=provenance.get("plan"),
            usage={"usage_seconds": provenance.get("usage_seconds")}
            if provenance.get("usage_seconds") is not None else None)
        self._note_quantum_success()
        batch_id = provenance.get("batch_id")
        self._emit("random_batch", outcome=mca_events.OUTCOME_SUCCESS,
                   reason_code=None, stage="receive",
                   provider=PROVIDER_ID_IBM,
                   entity_ids={"batch_id": batch_id},
                   duration_ms=batch.latency_ms)
        await self._prune_bounded()
        return {"ok": True, "batch_id": batch_id,
                "length": len(batch.values)}

    async def _prune_bounded(self) -> None:
        if self._store is None:
            return
        try:
            await self._store.prune(
                retention_days=mca_gates.random_draw_retention_days(),
                max_rows=mca_gates.random_draw_max_rows())
        except Exception:
            logger.warning("[random_source] prune failed", exc_info=True)

    # ── IBM durable job (существующий task_jobs; без нового store) ─────────
    @staticmethod
    def _utc_day_start(now: float | None = None) -> int:
        ts = float(now if now is not None else time.time())
        day = datetime.fromtimestamp(ts, tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        return int(day.timestamp())

    async def _ibm_task_rows(self, *, statuses=None, since: int | None = None,
                             limit: int | None = None) -> list[dict]:
        if self.db is None:
            return []
        sql = "SELECT * FROM task_jobs WHERE kind = ?"
        params: list = [IBM_JOB_KIND]
        statuses = tuple(str(s) for s in (statuses or ()) if str(s))
        if statuses:
            sql += " AND status IN (" + ",".join("?" * len(statuses)) + ")"
            params.extend(statuses)
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(int(since))
        sql += " ORDER BY created_at DESC, job_id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        try:
            cursor = await self.db.db.execute(sql, tuple(params))
            return [dict(row) for row in await cursor.fetchall()]
        except Exception:
            logger.warning("[random_source] ibm task read failed",
                           exc_info=True)
            return []

    async def _ibm_active_jobs(self) -> list[dict]:
        # `interrupted` — строка, снятая watchdog'ом, но IBM job мог остаться
        # живым: до recovery это тоже «в работе», иначе возможен дубль оплаты.
        return await self._ibm_task_rows(
            statuses=("queued", "running", "interrupted"))

    async def _ibm_jobs_today(self) -> int:
        rows = await self._ibm_task_rows(since=self._utc_day_start())
        return len(rows)

    async def _ibm_usage_today(self) -> float:
        rows = await self._ibm_task_rows(
            statuses=("completed",), since=self._utc_day_start())
        total = 0.0
        for row in rows:
            ref = row.get("result_ref")
            if not ref:
                continue
            try:
                data = json.loads(str(ref))
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            raw = data.get("usage")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                total += value
        return total

    @staticmethod
    def _ibm_cursor(row: dict) -> dict:
        payload = row.get("payload")
        if not payload:
            return {}
        try:
            data = json.loads(str(payload))
        except (TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        cursor = data.get("cursor")
        if isinstance(cursor, dict):
            return dict(cursor)
        if isinstance(cursor, str) and cursor.strip():
            try:
                parsed = json.loads(cursor)
            except (TypeError, ValueError):
                return {"job": cursor.strip()}
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}

    async def _ibm_jobs_snapshot(self, *, limit: int = 8) -> list[dict]:
        rows = await self._ibm_task_rows(limit=limit)
        out: list[dict] = []
        for row in rows:
            cursor = self._ibm_cursor(row)
            out.append({
                "job_id": row.get("job_id"),
                "ibm_job_id": cursor.get("job"),
                "status": row.get("status"),
                "state": cursor.get("state"),
                "backend": cursor.get("backend"),
                "attempt": row.get("attempt"),
                "error_code": row.get("error_code"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "finished_at": row.get("finished_at"),
            })
        return out

    async def _ibm_batch_exists(self, ibm_job_id: str) -> bool:
        if self.db is None or not str(ibm_job_id or "").strip():
            return False
        needle = f'"job":"{str(ibm_job_id).strip()}"'
        try:
            cursor = await self.db.db.execute(
                "SELECT 1 FROM mca_random_batches WHERE provider = ? "
                "AND instr(COALESCE(external_ref, ''), ?) > 0 LIMIT 1",
                (PROVIDER_ID_IBM, needle))
            return await cursor.fetchone() is not None
        except Exception:
            logger.warning("[random_source] ibm batch lookup failed",
                           exc_info=True)
            return False

    async def _ibm_deposit_batch(self, batch: AnuBatch,
                                 fingerprint: str | None = None) -> str:
        if self._store is None:
            raise IbmError("provider_unavailable", "store unavailable",
                           stage="deposit", sent=False)
        provenance = dict(batch.provenance or {})
        ref = _ibm_external_ref(provenance)
        batch_id = await self._store.insert_batch(
            batch,
            config_fingerprint=(fingerprint if fingerprint is not None
                                else self._ibm_config_fingerprint()),
            external_ref=ref)
        batch.provenance["batch_id"] = batch_id
        return batch_id

    async def _finish_ibm_row(self, row: dict, *, status: str,
                              reason_code: str | None = None,
                              result_ref: str | None = None,
                              error_code: str | None = None) -> None:
        if self.db is None:
            return
        from services.task_supervisor import TaskJobStore
        try:
            await TaskJobStore(self.db).finish(
                str(row.get("job_id") or ""), status=status,
                reason_code=reason_code, result_ref=result_ref,
                error_code=error_code, recovery=True)
        except Exception:
            logger.warning("[random_source] ibm row finish failed | "
                           "job_id=%s", row.get("job_id"), exc_info=True)

    async def _recover_ibm_jobs(self) -> int:
        """Присоединиться к незавершённым IBM job'ам после рестарта.

        Только poll/attach по сохранённому job ID. Если ID нет (сбой между
        submit и checkpoint), job НЕ отправляется повторно: строка честно
        закрывается `submit_uncertain`. Поздний результат зачисляется в
        durable-пул; уже зачисленная партия не дублируется."""
        if not (mca_gates.random_source_enabled()
                and mca_gates.random_quantum_enabled()):
            return 0
        if not self._ibm_configured() or not self._ibm_dependency_available():
            return 0
        current_fp = self._ibm_config_fingerprint()
        # Поздний результат ищем и у уже закрытых строк: timeout/failed/
        # expired — это локальная точка зрения, а не приговор IBM job'у.
        since = int(time.time()) - max(
            int(self._ibm_job_max_age()) * 2, 86400)
        rows = await self._ibm_task_rows(
            statuses=("queued", "running", "interrupted", "failed",
                      "expired"),
            since=since)
        started = 0
        for row in rows:
            cursor = self._ibm_cursor(row)
            purpose = str(cursor.get("purpose") or "refill")
            ibm_job_id = str(cursor.get("job") or "").strip()
            if not ibm_job_id:
                job_tag = str(cursor.get("job_tag") or "").strip()
                resolved = None
                if job_tag and self._ibm_configured():
                    try:
                        resolved = await self._get_ibm_client() \
                            .find_job_by_tag(
                                api_key=self._ibm_api_key(),
                                crn=self._ibm_crn(),
                                instance=self._ibm_instance(),
                                region=self._ibm_region(),
                                channel=self._ibm_channel(),
                                tag=job_tag)
                    except Exception:
                        resolved = None
                if resolved:
                    ibm_job_id = str(resolved)
                    cursor = dict(cursor)
                    cursor["job"] = ibm_job_id
                    cursor["state"] = IBM_JOB_SUBMITTED
                    from services.task_supervisor import TaskJobStore
                    await TaskJobStore(self.db).save_checkpoint(
                        str(row.get("job_id") or ""),
                        cursor_token=json.dumps(
                            cursor, separators=(",", ":"),
                            ensure_ascii=False),
                        processed=0)
                else:
                    if str(row.get("reason_code") or "") != \
                            "submit_uncertain":
                        await self._finish_ibm_row(
                            row, status="failed",
                            reason_code="submit_uncertain",
                            error_code="delivery_unknown")
                    continue
            cursor_fp = str(cursor.get("config_fp") or "").strip()
            if cursor_fp and current_fp and cursor_fp != current_fp:
                await self._finish_ibm_row(
                    row, status="failed", reason_code="config_changed",
                    error_code="config_changed")
                continue
            if purpose != "smoke" and await self._ibm_batch_exists(
                    ibm_job_id):
                await self._finish_ibm_row(
                    row, status="completed", reason_code="recovered_pool",
                    result_ref="recovered_existing_batch")
                continue
            if ibm_job_id in self._ibm_recovering:
                continue
            task = asyncio.create_task(
                self._recover_ibm_job(row=row, cursor=cursor,
                                      ibm_job_id=ibm_job_id))
            self._ibm_recovering.add(ibm_job_id)
            self._ibm_recovery_tasks.add(task)

            def _done(_t, jid=ibm_job_id):
                self._ibm_recovering.discard(jid)
                self._ibm_recovery_tasks.discard(_t)

            task.add_done_callback(_done)
            started += 1
        return started

    async def _recover_ibm_job(self, *, row: dict, cursor: dict,
                               ibm_job_id: str) -> None:
        from services.task_supervisor import TaskJobStore
        try:
            if self.db is None:
                return
            purpose = str(cursor.get("purpose") or "refill")
            batches = await self._get_ibm_client().resume(
                api_key=self._ibm_api_key(), crn=self._ibm_crn(),
                instance=self._ibm_instance(), region=self._ibm_region(),
                channel=self._ibm_channel(), job_id=ibm_job_id,
                shots=int(cursor.get("shots") or 0),
                num_qubits=int(cursor.get("qubits") or 0),
                requested=int(cursor.get("values")
                              or (1 if purpose == "smoke"
                                  else self._batch_length())),
                submitted_at=int(cursor.get("submitted_at")
                                 or row.get("created_at") or time.time()),
                plan=cursor.get("plan"),
                deposit=(None if purpose == "smoke"
                         else self._ibm_deposit_batch),
                job_store=TaskJobStore(self.db))
            provenance = dict((batches.provenance if batches else {}) or {})
            await self._finish_ibm_row(
                row, status="completed", reason_code="recovered",
                result_ref=_ibm_external_ref(provenance))
            self._note_ibm_success(
                latency_ms=batches.latency_ms,
                job={"job_id": ibm_job_id,
                     "backend": provenance.get("backend"),
                     "state": IBM_JOB_COMPLETED},
                plan=provenance.get("plan"),
                usage={"usage_seconds": provenance.get("usage_seconds")}
                if provenance.get("usage_seconds") is not None else None)
        except IbmError as exc:
            state = str(exc.job_state or "")
            status = ("cancelled" if state == IBM_JOB_CANCELLED
                      else "failed")
            await self._finish_ibm_row(
                row, status=status,
                reason_code=("expired" if state == IBM_JOB_EXPIRED
                             else exc.code),
                error_code=exc.code)
            self._note_ibm_failure(exc.code, stage=exc.stage)
        except Exception as exc:      # pragma: no cover - fail-open
            await self._finish_ibm_row(
                row, status="failed", reason_code="recovery_failed",
                error_code=type(exc).__name__)
            logger.warning("[random_source] ibm recovery failed",
                           exc_info=True)
        finally:
            self._ibm_recovering.discard(ibm_job_id)

    async def startup(self) -> dict:
        """Один refill/активация при старте (K1/K2 ON).

        Цель P3 — первый запрашиваемый провайдер действующего порядка:
        ANU (действующий ключ) — прежняя активация/self-check; LfDR — только
        фоновое пополнение общего запаса (активации/ANU-state у него нет);
        IBM до P5 недоступен. Fail-open (ошибка не роняет старт).

        Перед решением — идемпотентный backfill `config_fingerprint` легаси-
        партий ANU (arch P1 D2): старт после миграции v48 — единственная
        гарантированная точка, где доступен и durable state, и действующий
        ключ. Ошибка backfill не блокирует старт."""
        try:
            if not mca_gates.random_source_enabled() or \
                    not mca_gates.random_quantum_enabled():
                return {"status": "disabled"}
            # P5: сначала присоединиться к незавершённым IBM job'ам по
            # сохранённому job ID (poll/attach, без повторной отправки).
            recovered = 0
            try:
                recovered = await self._recover_ibm_jobs()
            except Exception:
                logger.warning("[random_source] ibm recovery failed — "
                               "fail-open", exc_info=True)
            target = await self._refill_target()
            if target is None:
                if self._ibm_configured() and \
                        not self._ibm_dependency_available():
                    return {"status": "blocked",
                            "reason": "dependency_missing"}
                if not self._resolve_key():
                    await self._mark_state_failure("provider_unconfigured")
                    return {"status": "blocked",
                            "reason": "provider_unconfigured"}
                return {"status": "blocked", "reason": "provider_unavailable"}
            if target == PROVIDER_ID_ANU:
                state = await self._read_state()
                fingerprint = key_fingerprint(self._resolve_key())
                active = bool(state and state.get("activated_at")
                              and state.get("key_fingerprint") == fingerprint)
                if active:
                    await self.sync_batch_provenance()
                if not active:
                    result = await self.activate(manual=False)
                    return {"status": "activated" if result.get("activated")
                            else "blocked",
                            "reason": result.get("blocker"),
                            "state": result.get("state")}
            reserve = await self._provider_reserve_map()
            remaining = int(reserve.get(target, 0) or 0)
            if remaining < self._low_watermark():
                if target == PROVIDER_ID_IBM:
                    # QPU-очередь не входит в критический путь старта:
                    # задание уходит в фон (существующий TaskSupervisor).
                    self._schedule_refill()
                    return {"status": "scheduled", "provider": target,
                            "remaining": remaining}
                result = await self.refill_if_needed()
                return {"status": result.get("status"),
                        "reason": result.get("reason"),
                        "provider": target}
            return {"status": "ok", "remaining": remaining,
                    "provider": target}
        except Exception:
            logger.warning("[random_source] startup failed — fail-open",
                           exc_info=True)
            return {"status": "error", "reason": "provider_unavailable"}

    # ── статус/видимость (контракт для блоков D/mca-17c) ───────────────────
    async def anu_state(self) -> str:
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return ANU_STATE_DISABLED
        key = self._resolve_key()
        if not key:
            return ANU_STATE_UNCONFIGURED
        state = await self._read_state()
        if (state is None or not state.get("activated_at")
                or state.get("key_fingerprint") != key_fingerprint(key)):
            return ANU_STATE_UNVERIFIED
        reason = str(state.get("last_fallback_reason") or "")
        if reason == "quota_exhausted":
            return ANU_STATE_QUOTA
        if reason in _DEGRADED_REASONS:
            return ANU_STATE_DEGRADED
        return ANU_STATE_ACTIVE

    async def status_snapshot(self, chat_id=None) -> dict:
        """R17-safe статус (без ключа/сырого текста/отпечатков): selected/
        effective, состояние ANU, запас, последнее пополнение, счётчики,
        fallback.

        Provenance (arch P1 D1/G4, без UI): канонический `provider` +
        `entropy_class` (только когда квантовая случайность фактически
        действует), реестр трёх провайдеров, per-provider расходуемый остаток
        (strict F4) и `quarantined` (партии другой конфигурации). История
        (`last_batch`) не переписывается — рядом `provider_id` и
        `config_matches`; сам `config_fingerprint` НАРУЖУ НЕ ОТДАЁТСЯ (F2:
        он совпадает с `state.key_fingerprint`, а `/api/status` доступен
        без permission).

        QRNG P3 (arch D4/D5/D6): селектор (`primary_provider`,
        `primary_setting_raw/_state`, `fallback_enabled/order`), фактический
        `resolved_primary`/`effective_provider`, явный PRNG-режим
        (`fallback_setting`+`prng_active`). Снятое сохранённое значение
        показывается КАК ЕСТЬ со state `requires_resolution` — статус не
        подменяет его фактическим выбором."""
        selection = await self.resolve_selection(chat_id)
        effective = selection.mode
        blocker = selection.blocker
        state = await self._read_state() or {}
        last_batch_raw = None
        stats = {"quantum": 0, "pseudorandom": 0}
        quota = None
        consumable: dict = {}
        stock: dict = {}
        if self._store is not None:
            try:
                last_batch_raw = await self._store.last_batch_info()
                stats = await self._store.journal_stats()
                quota = await self._store.quota_get(
                    account_key=self._account_key())
                consumable = await self._provider_reserve_map()
                stock = await self._store.provider_reserve()
            except Exception:
                pass
        last_batch = None
        if last_batch_raw is not None:
            public_fields = (
                "batch_id", "provider", "data_type", "length",
                "reserved_upto", "consumed_upto", "created_at", "external_ref")
            last_batch = {k: last_batch_raw.get(k) for k in public_fields}
            last_batch["provider_id"] = canonical_provider_id(
                last_batch_raw.get("provider"))
            last_batch["config_matches"] = config_matches(
                last_batch_raw.get("config_fingerprint"),
                self._provider_fingerprint(last_batch["provider_id"]))
        reserve_by_provider = {pid: int(consumable.get(pid, 0) or 0)
                               for pid in PROVIDER_IDS}
        quarantined_by_provider = {
            pid: max(0, int(stock.get(pid, 0) or 0) - reserve_by_provider[pid])
            for pid in PROVIDER_IDS}
        key_present = bool(self._resolve_key())
        anu_state = await self.anu_state()
        quantum = effective == MODE_QUANTUM
        lfdr_state = self._lfdr_state()
        lfdr_status = (self._lfdr_client.status()
                       if self._lfdr_client is not None else None)
        ibm_state = self._ibm_state()
        ibm_status = (self._ibm_client.status()
                      if self._ibm_client is not None else None)
        ibm_jobs = await self._ibm_jobs_snapshot()
        providers = []
        for pid in PROVIDER_IDS:
            spec = PROVIDERS[pid]
            configured = self.provider_configured(pid)
            reserve = reserve_by_provider[pid]
            provider_state = ANU_STATE_UNCONFIGURED
            extra: dict = {}
            if pid == PROVIDER_ID_ANU:
                provider_state = anu_state
            elif pid == PROVIDER_ID_LFDR:
                provider_state = lfdr_state
                extra = {
                    "last_error": self._lfdr_health.get("last_error"),
                    "last_success_at": self._lfdr_health.get(
                        "last_success_at"),
                    "last_failure_at": self._lfdr_health.get(
                        "last_failure_at"),
                    "breaker": lfdr_status,
                }
            elif pid == PROVIDER_ID_IBM:
                provider_state = ibm_state
                extra = {
                    "last_error": self._ibm_health.get("last_error"),
                    "last_stage": self._ibm_health.get("last_stage"),
                    "last_success_at": self._ibm_health.get(
                        "last_success_at"),
                    "last_failure_at": self._ibm_health.get(
                        "last_failure_at"),
                    "breaker": ibm_status,
                    "last_job": self._ibm_health.get("last_job"),
                    "jobs": ibm_jobs,
                    "plan": self._ibm_health.get("plan"),
                    "usage": self._ibm_health.get("usage"),
                    "key_present": bool(self._ibm_api_key()),
                    "crn_present": bool(self._ibm_crn()),
                    "dependency": self._ibm_dependency_available(),
                    "max_inflight": self._ibm_max_inflight(),
                    "max_jobs_per_day": self._ibm_max_jobs_per_day(),
                    "max_qpu_seconds_per_day":
                        self._ibm_max_qpu_seconds_per_day(),
                }
            providers.append({
                "id": spec.id,
                "title": spec.title,
                "entropy_class": spec.entropy_class,
                "requires_key": bool(spec.requires_key),
                # `configured` — наличие всех ПРЕДУСЛОВИЙ запроса (ANU —
                # действующий ключ; LfDR — ключ не требуется, публичный
                # endpoint и адаптер P2 есть), НЕ health/наличие значений.
                # IBM в P3 без IAM/instance/CRN (P5) → False: фейкового
                # зелёного нет. Здоровье — `state` (lfdr: unverified/active/
                # degraded/disabled), наличие значений — `consumable`.
                "configured": bool(configured),
                # `reserve` — расходуемый остаток действующей конфигурации;
                # `quarantined` — физический остаток другой конфигурации;
                # `consumable` — есть ли что расходовать сейчас.
                "reserve": reserve,
                "consumable": reserve > 0,
                "quarantined": quarantined_by_provider[pid],
                "config_matches": quarantined_by_provider[pid] == 0,
                "state": provider_state,
                **extra,
            })
        prng_setting = await self.fallback_enabled(chat_id)
        return {
            "selected_source": selection.selected_mode,
            "effective_source": effective,
            "fallback_reason": blocker,
            # T-5261 (asap5-final-fixes, §14): настройка fallback — проверяемое
            # поле config-state (владелец видит, что PRNG-откаты разрешены).
            # QRNG P1 (arch D6/FALL-02): значение НЕ перезаписывается, но
            # отдаётся явно как «псевдослучайный откат (не квантовый)».
            "fallback_setting": prng_setting,
            "fallback_setting_label": "псевдослучайный откат (не квантовый)",
            # QRNG P3: PRNG-режим явный, а не скрытая подмена.
            "prng_active": bool(effective == MODE_PSEUDORANDOM
                                and selection.selected_mode == MODE_QUANTUM),
            "prng_setting": prng_setting,
            # ── селектор провайдера (arch D4/D5) ──────────────────────────
            "primary_provider": selection.primary_provider,
            "primary_setting_raw": selection.primary_setting_raw,
            "primary_setting_state": selection.primary_setting_state,
            "resolved_primary": selection.resolved_primary,
            "effective_provider": selection.effective_provider,
            "fallback_enabled": selection.fallback_enabled,
            "fallback_order": list(selection.fallback_order),
            "fallback_order_raw": selection.fallback_order_raw,
            "fallback_order_state": selection.fallback_order_state,
            "effective_order": list(selection.effective_order),
            "provider": selection.effective_provider,
            "entropy_class": (ENTROPY_CLASS_HARDWARE if quantum else None),
            "providers": providers,
            "provider_reserve": reserve_by_provider,
            "provider_quarantined": quarantined_by_provider,
            "reserve_quarantined": sum(quarantined_by_provider.values()),
            "anu_state": anu_state,
            "lfdr_state": lfdr_state,
            "ibm_state": ibm_state,
            "ibm_jobs": ibm_jobs,
            "ibm_last_job": self._ibm_health.get("last_job"),
            "ibm_plan": self._ibm_health.get("plan"),
            "ibm_usage": self._ibm_health.get("usage"),
            "ibm_key_present": bool(self._ibm_api_key()),
            "ibm_crn_present": bool(self._ibm_crn()),
            "ibm_dependency": self._ibm_dependency_available(),
            "key_present": key_present,
            "key_fingerprint": state.get("key_fingerprint"),
            # Суммарный расходуемый запас (все провайдеры действующей
            # конфигурации) — одно число «сколько квантовых значений есть».
            "reserve_remaining": sum(reserve_by_provider.values()),
            "buffer_max": self._buffer_max(),
            "low_watermark": self._low_watermark(),
            "last_batch": last_batch,
            "draws": stats,
            "quota": quota,
            "last_fallback_reason": state.get("last_fallback_reason"),
            "last_fallback_at": state.get("last_fallback_at"),
            "activated_at": state.get("activated_at"),
            "plan": self._plan(),
            "policy_version": POLICY_VERSION,
            "source_impl": SOURCE_IMPL_PRNG,
            "python_version": platform.python_version(),
        }

    async def quota_snapshot(self) -> dict:
        """Квота ANU (глобальная, не per-chat): локальный учёт; точный остаток
        — только при авторитетных данных, иначе честная «оценка».

        Period-aware (F-1): если durable-строка относится к прошлому периоду,
        снимок показывает нулевые счётчики текущего периода (read-only, без
        записи) — «оценка» не залипает на исчерпании прошлого месяца."""
        plan = self._plan()
        period = _utc_period()
        row = None
        if self._store is not None:
            try:
                row = await self._store.quota_get(
                    account_key=self._account_key())
            except Exception:
                row = None
        row = row or {}
        stale = str(row.get("period") or "") != period
        success = 0 if stale else int(row.get("success") or 0)
        failed = 0 if stale else int(row.get("failed") or 0)
        unknown = 0 if stale else int(row.get("unknown") or 0)
        manual = 0 if stale else int(row.get("manual_checks") or 0)
        used = success + failed + unknown + manual
        limit = (mca_gates.random_anu_trial_monthly_limit()
                 if plan == "Trial" else None)
        remaining = (max(0, int(limit) - used)
                     if limit is not None else None)
        return {
            "account_key": self._account_key(),
            "period": period,
            "plan": plan,
            "success": success, "failed": failed, "unknown": unknown,
            "manual_checks": manual, "used": used,
            "limit": limit, "remaining": remaining,
            "estimate": True,     # авторитетных данных провайдера нет
            "last_success_at": None if stale else row.get("last_success_at"),
            "last_failure_at": None if stale else row.get("last_failure_at"),
            "last_reason": None if stale else row.get("last_reason"),
        }

    async def recent_draws(self, *, limit: int = 20,
                           chat_id: int | None = None) -> list[dict]:
        """Журнал draw (R17-safe: числа/ID/коды, без сырого текста)."""
        if self._store is None:
            return []
        try:
            return await self._store.recent_draws(limit=limit,
                                                  chat_id=chat_id)
        except Exception:
            return []

    # ── стык mca-06 (D7): async-фабрика + sync pick ────────────────────────
    async def build_dream_source(self, pipeline_run_id: int | None,
                                 *, k_hint: int = 10, chat_id=None):
        """K1 ON: core-адаптер с durably зарезервированным bounded chunk;
        fallback OFF + пусто → None (mca-06-семантика: ранжированный путь).

        QRNG P3: chunk берётся из первого провайдера действующего порядка, у
        которого есть расходуемый запас (не из «самой старой партии» вообще)."""
        await self.flush_journal()
        selection = await self.resolve_selection(chat_id)
        if selection.selected_mode == MODE_PSEUDORANDOM:
            return CoreDreamRandomSource(
                pipeline_run_id=pipeline_run_id, chat_id=chat_id,
                source=MODE_PSEUDORANDOM, provider=PROVIDER_PRNG,
                journal_sink=self._enqueue_journal)
        if not mca_gates.random_quantum_enabled():
            return await self._dream_fallback(pipeline_run_id, chat_id,
                                              "disabled")
        chunk_size = min(max(2 * int(k_hint) + 4, DREAM_CHUNK_MIN),
                         DREAM_CHUNK_MAX)
        if self._store is not None and selection.mode == MODE_QUANTUM:
            for pid in selection.effective_order:
                provider_ids = PROVIDER_STORAGE_IDS.get(pid)
                if provider_ids is None:
                    continue
                try:
                    chunk = await self._store.reserve_chunk(
                        chunk_size,
                        config_fingerprint=self._provider_fingerprint(pid),
                        provider_ids=provider_ids)
                except Exception:
                    logger.warning("[random_source] dream reserve failed",
                                   exc_info=True)
                    chunk = []
                if chunk:
                    first = chunk[0]
                    return CoreDreamRandomSource(
                        pipeline_run_id=pipeline_run_id, chat_id=chat_id,
                        source=MODE_QUANTUM, provider=first.provider,
                        batch_id=first.batch_id, data_type=first.data_type,
                        values=[c.value for c in chunk],
                        draw_ids=[c.draw_id for c in chunk],
                        journal_sink=self._enqueue_journal)
        blocker = selection.blocker or await self._resolution_blocker(
            selection.resolved_primary)
        if self._auto_refill:
            self._schedule_refill()
        return await self._dream_fallback(pipeline_run_id, chat_id, blocker)

    async def _dream_fallback(self, pipeline_run_id, chat_id, blocker):
        if await self.fallback_enabled(chat_id):
            self._note_transition(key=f"prng:{blocker}", reason=blocker)
            await self._mark_fallback(blocker)
            return CoreDreamRandomSource(
                pipeline_run_id=pipeline_run_id, chat_id=chat_id,
                source=MODE_PSEUDORANDOM, provider=PROVIDER_PRNG,
                fallback=True, fallback_reason=blocker,
                journal_sink=self._enqueue_journal)
        self._note_transition(key=f"defer:{blocker}", reason=blocker,
                              deferred=True)
        return None

    def _schedule_refill(self) -> None:
        if not (mca_gates.random_source_enabled()
                and mca_gates.random_quantum_enabled()
                and mca_gates.random_refill_enabled()):
            return
        if self._store is None or self.db is None:
            return
        if self._refill_task is not None and not self._refill_task.done():
            return
        # QRNG P3: наличие ANU-ключа больше не единственное условие — цель
        # (ANU/LfDR) выбирает refill_if_needed по действующему порядку; нет
        # запрашиваемого провайдера → честный blocked, без сети.
        async def _runner():
            try:
                await self.refill_if_needed()
            except Exception:
                logger.warning("[random_source] background refill failed",
                               exc_info=True)

        try:
            self._refill_task = asyncio.create_task(_runner())
        except RuntimeError:       # нет running loop (sync-контекст)
            self._refill_task = None


# ── модульный синглтон + точки входа ────────────────────────────────────────
_service: RandomSourceService | None = None


def get_service(db=None) -> RandomSourceService:
    global _service
    if _service is None:
        _service = RandomSourceService(db)
    elif db is not None and _service.db is None:
        _service.bind_db(db)
    return _service


def bind_db(db) -> RandomSourceService:
    return get_service(db)


def reset_service() -> None:
    """Сброс синглтона (тесты)."""
    global _service
    _service = None


async def startup() -> dict:
    """Точка входа старта бота (fail-open; K1/K2 OFF → no-op)."""
    return await get_service().startup()


async def for_dream(pipeline_run_id: int | None, *, k_hint: int = 10,
                    chat_id=None):
    """Async-фабрика стыка mca-06 (D7). K1 OFF → ровно `default_source`
    (бит-в-бит 2.58.57); ошибка контура → детерминированный default."""
    try:
        if not mca_gates.random_source_enabled():
            return mca_dream_random.default_source(pipeline_run_id)
        return await get_service().build_dream_source(
            pipeline_run_id, k_hint=k_hint, chat_id=chat_id)
    except Exception:
        logger.warning("[random_source] for_dream failed — deterministic "
                       "default", exc_info=True)
        return mca_dream_random.default_source(pipeline_run_id)
