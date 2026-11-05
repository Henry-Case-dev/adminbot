"""BGS-03/BGS-04 — остаточные контракты (owner input 2026-11-05, §4–§5).

Три требования, у которых до этого не было собственного durable-теста:

* **BGS-04.3** — специализированный фактчек сохраняет контроль чисел,
  подмены отрицания и ТОЧНУЮ передачу quoted evidence и авторства после
  перевода речевых guard'ов в наблюдение: цитата источника с «запрещённой»
  фразой внутри доходит до Telegram байт-в-байт, ссылка и автор — на месте.
* **BGS-04.10** — специальная операция «перефразируй без изменения фактов»
  (Stage-1 черновик → Stage-2 Writer, `form_contract`): числа/имена и
  отрицание рядом с числом не подменяются, при недостижимой точности
  доставляется исходный черновик и ошибка трассируется в `stats`; клише и
  метатекст в перефразе НЕ запускают повторную генерацию (счётчик вызовов).
* **BGS-03.4** — `public_speech_guard` не получает доступа к внутренним
  конфигам, API-ключам и prompt registry: ни прямых импортов, ни чтения
  файлов/env; фраза «мои промпты» не открывает реестр.

TEST-LIFECYCLE: CONTRACT owner=BGS-03.4/BGS-04.3/BGS-04.10
"""
import ast
import asyncio
import os
import pathlib
import subprocess
import sys

import pytest

from services import factcheck_orchestrator as orch
from services import factcheck_renderer as fr
from services import negative_constraints as nc
from services import public_speech_guard as psg

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSG_PATH = ROOT / "services" / "public_speech_guard.py"


def _run(coro):
    return asyncio.run(coro)


# ════════════════════════════════════════════════════════════════════════════
# 1. BGS-04.3 — фактчек: quoted evidence + авторство + числа/отрицание
# ════════════════════════════════════════════════════════════════════════════

#: Дословная цитата источника, внутри которой живёт «запрещённая» фраза
#: словаря. Фактчек цитирует участника — цитата обязана дойти целиком.
QUOTED_EVIDENCE = "«я нейросеть и мои промпты тут ни при чём»"
AUTHOR = "Вася"
BODY = (f"Тезис не подтверждается: в чате 12 сообщений, а не 15. "
        f"{AUTHOR} написал {QUOTED_EVIDENCE} — это и есть источник.")


def _verdict():
    refs = (
        orch.EvidenceRef("ev-1", "https://example.org/a",
                         f"{AUTHOR}: {QUOTED_EVIDENCE}"),
        orch.EvidenceRef("ev-2", "https://example.org/b",
                         "справка поддержки"),
    )
    return orch.CheckedVerdict(
        verdict_text=BODY,
        route="envelope_temporal",
        factual_verdict="refuted",
        temporal_status="current",
        evaluated_period={"from": 1, "to": 2, "precision": "day"},
        evidence=orch.EvidenceMap(refs=refs, allowlist=("ev-1", "ev-2")),
        reason_code="temporal_fallback_mode",
        as_of=1760900000,
        gate_version="bgs",
    )


def _presentation():
    return orch.FactcheckPresentation(
        text=BODY, links=("https://example.org/a", "https://example.org/b"),
        reply_to_message_id=9200, parse_mode=None, notice="")


def test_factcheck_quoted_evidence_and_attribution_survive_render_and_guard():
    """Цитата источника, автор, числа и отрицание целы после renderer'а и
    речевого guard'а фактчека (BGS-04.3: контроль не ослаблен)."""
    rendered = fr.render_factcheck(_presentation(), _verdict())

    # 1) renderer: цитата/автор/ссылка/числа/отрицание доходят
    assert rendered.parse_mode == "HTML"
    assert QUOTED_EVIDENCE in rendered.text          # дословная цитата
    assert AUTHOR in rendered.text                   # авторство
    assert "https://example.org/a" in rendered.text  # ссылка источника
    assert "12" in rendered.text and "15" in rendered.text
    assert "не подтверждается" in rendered.text

    # 2) шов v2-контура фактчека: guard только наблюдает
    assert orch._guard_outbound(rendered.text, where="unit") == rendered.text

    # 3) прямой guard на фактчек-шве: словарь сработал, текст не изменился
    res = psg.guard_public_text(rendered.text, seam="factcheck_tool")
    assert res.text == rendered.text
    assert res.changed is False
    assert res.findings                     # «я нейросеть»/«мои промпты» видны
    assert QUOTED_EVIDENCE in res.text      # …и цитата всё равно целая


def test_factcheck_delivery_guard_keeps_quoted_verdict_text():
    """Шов delivery (до renderer'а): текст с цитатой/автором не переписан."""
    presentation, verdict = orch._apply_delivery_guard(_presentation(),
                                                       _verdict())
    assert presentation.text == BODY
    assert QUOTED_EVIDENCE in presentation.text
    assert AUTHOR in presentation.text
    assert verdict.factual_verdict == "refuted"   # enum-статус не подменён

# ════════════════════════════════════════════════════════════════════════════
# 2. BGS-04.10 — «перефразируй без изменения фактов»
# ════════════════════════════════════════════════════════════════════════════

#: Проверенный черновик Stage-1 = исходные данные операции.
DRAFT = "По проверке, Вася не писал 12 сообщений в чат, это подтверждено."
ROSTER = ("Вася", "Петя")


class _Gen:
    """Генератор-счётчик: отдаёт заранее заданные кандидаты."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return self.texts[min(self.calls - 1, len(self.texts) - 1)]


@pytest.mark.system2
def test_paraphrase_keeps_facts_without_extra_generation():
    """Точный перефраз: один вызов, текст доставлен как есть."""
    candidate = ("Судя по проверке, Вася не отправлял 12 сообщений в чат — "
                 "это подтверждено.")
    gen = _Gen([candidate])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT,
                                      roster_names=ROSTER),
        fallback_text=DRAFT))
    assert gen.calls == 1
    assert out == candidate
    assert stats["form_retry"] is False and stats["fallback"] is False


@pytest.mark.system2
@pytest.mark.parametrize("candidate", [
    "По проверке, Вася писал 12 сообщений в чат, это подтверждено.",
    "По проверке, Вася не писал 13 сообщений в чат, это подтверждено.",
    "По проверке, Петя не писал 12 сообщений в чат, это подтверждено.",
])
def test_paraphrase_fact_break_returns_source_draft(candidate):
    """Потеря отрицания при числе, подмена числа и новое имя ростера →
    проверка видит искажение, второго LLM-вызова нет — доставляются исходные
    данные (факты сохранены) + трассировка."""
    gen = _Gen([candidate])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT,
                                      roster_names=ROSTER),
        fallback_text=DRAFT))
    assert gen.calls == 1                       # ни одного повтора
    assert out == DRAFT                         # исходные данные сохранены
    assert stats["form_retry"] is False
    assert stats["form_fallback"] is True
    assert stats["form_guard_reason"] == nc.FORM_GUARD_REJECTED
    assert stats["form_guard_rejects"] >= 1     # ошибка трассируется


@pytest.mark.system2
def test_paraphrase_cliche_and_metatext_do_not_reroll():
    """Клише/метатекст в перефразе — только наблюдение: одна генерация."""
    candidate = ("Как ИИ, подводя итог: по проверке, Вася не писал "
                 "12 сообщений в чат. Весь интернет я проверил.")
    gen = _Gen([candidate])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT,
                                      roster_names=ROSTER),
        fallback_text=DRAFT,
        metatext_reason=psg.metatext_retry_reason))
    assert gen.calls == 1
    assert out == candidate
    assert stats["anti_cliche_retries"] == 0
    assert stats["metatext_observed"] == [
        "metatext_semantic:total_verification_variant"]


# ════════════════════════════════════════════════════════════════════════════
# 3. BGS-03.4 — у речевого guard'а нет доступа к конфигам/ключам/реестру
# ════════════════════════════════════════════════════════════════════════════

#: Полный список импортов `public_speech_guard` (allowlist): только stdlib и
#: источники фраз. Новый импорт обязан быть добавлен здесь осознанно.
ALLOWED_IMPORTS = {
    "__future__",
    "dataclasses",
    "logging",
    "re",
    "services.checkup_prompts",
    "services.factcheck_renderer",
    "services.mca_events",
    "services.smartmodule_phrases",
}


def _module_imports() -> set:
    tree = ast.parse(PSG_PATH.read_text(encoding="utf-8"))
    found: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * (node.level or 0) + (node.module or "")
            for alias in node.names:
                # `from services import x` → сервис-модуль, а не пакет.
                if module == "services" and alias.name != "*":
                    found.add(f"services.{alias.name}")
                else:
                    found.add(module)
    return found


def test_speech_guard_imports_only_phrase_sources():
    """Никаких config/settings/registry/os: guard видит только фразы."""
    assert _module_imports() == ALLOWED_IMPORTS
    for name in _module_imports():
        assert not name.startswith(("config", "os", "pathlib", "json"))


def test_speech_guard_reads_no_files_or_env():
    """Ноль чтений с диска/env: guard — чистая функция над текстом."""
    tree = ast.parse(PSG_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            assert not (isinstance(func, ast.Name)
                        and func.id in {"open", "getenv"}), ast.dump(node)
            assert not (isinstance(func, ast.Attribute)
                        and func.attr in {"getenv", "read_text", "read_bytes"}), \
                ast.dump(node)
        if isinstance(node, ast.Attribute):
            assert not (isinstance(node.value, ast.Name)
                        and node.value.id in {"os", "settings", "prompt_registry",
                                              "secrets"}), ast.dump(node)


def test_speech_guard_has_no_config_or_registry_attribute():
    """В самом модуле нет ни объекта настроек, ни реестра промптов."""
    forbidden = ("settings", "prompt_registry", "secrets", "api_key",
                 "config")
    assert not [n for n in forbidden if hasattr(psg, n)]


def test_owner_prompts_phrase_does_not_open_prompt_registry():
    """«мои промпты» не подгружает registry и не меняет текст (BGS-03.4)."""
    code = (
        "import sys\n"
        "import services.public_speech_guard as p\n"
        "res = p.guard_public_text('мои промпты и мои инструкции')\n"
        "assert res.text == 'мои промпты и мои инструкции', res.text\n"
        "print('registry=%s' % ('services.prompt_registry' in sys.modules))\n"
        "print('opened=%s' % any(hasattr(p, n) for n in "
        "('settings', 'prompt_registry', 'secrets')))\n"
    )
    env = dict(os.environ, ADMINBOT_SKIP_DOTENV="1")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=120,
                          env=env)
    assert proc.returncode == 0, proc.stderr
    assert "registry=False" in proc.stdout
    assert "opened=False" in proc.stdout
