"""FIX-W3: снять RED-поведение (до фикса) на текущем кандидате — F1–F4.

Временно возвращает до-фиксовые фрагменты `services/style_policy.py`
(JSON-спаны, слияние сегментов, json-ветка кавычек, локальная правка повтора)
и `services/direct_chat_service.py` (F3 payload-проверка до egress-guard, F4
проход в generate_initiative_reply вместо единой точки отправки), прогоняет
зонды, затем восстанавливает оба файла из бэкапа и сверяет sha256.
Никаких коммитов; при несовпадении sha — аварийный выход.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Code\Python\adminbot")
SCRATCH = Path(r"C:\Users\main\.config\opencode\OpenCodeScratch"
               r"\adminbot-ccef72c25768\fix-w3")
STYLE = ROOT / "services" / "style_policy.py"
DIRECT = ROOT / "services" / "direct_chat_service.py"

OLD_JSON = '''def _json_spans(text: str) -> list[Span]:
    """Строки-блоки, целиком разбираемые как JSON (защита машинных данных)."""
    spans: list[Span] = []
    for match in re.finditer(r"(?m)^[ \\t]*([\\{\\[])", text):
        opener = match.group(1)
        closer = "}" if opener == "{" else "]"
        cursor = match.start(1)
        depth = 0
        in_string = False
        escaped = False
        for pos in range(cursor, min(len(text), cursor + 20000)):
            char = text[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    block = text[cursor:pos + 1]
                    try:
                        json.loads(block)
                    except Exception:
                        break
                    spans.append(Span(cursor, pos + 1, "json"))
                    break
        else:
            continue
    return spans'''

OLD_MERGE = '''def _merge_spans(spans: Sequence[Span]) -> tuple[Span, ...]:
    """Слить пересечения: приоритет по :data:`_SPAN_PRIORITY`."""
    if not spans:
        return ()
    order = {kind: index for index, kind in enumerate(_SPAN_PRIORITY)}
    ranked = sorted(spans, key=lambda s: (s.start, order.get(s.kind, 99),
                                          -(s.end - s.start)))
    merged: list[Span] = []
    for span in ranked:
        if span.end <= span.start:
            continue
        overlap = None
        for index, kept in enumerate(merged):
            if span.start < kept.end and span.end > kept.start:
                overlap = index
                break
        if overlap is None:
            merged.append(span)
            continue
        kept = merged[overlap]
        winner = kept if order.get(kept.kind, 99) <= order.get(span.kind, 99) \\
            else span
        merged[overlap] = winner
    return tuple(sorted(merged, key=lambda s: s.start))'''

NEW_QUOTE_BRANCH = '''    unpaired = len(unpaired_positions)
    if not found and not unpaired:
        protected_machine = _protected_machine_quotes(text, spans, pairs)
        if protected_machine:
            return (STATUS_EXEMPTED, None, "protected_verbatim",
                    {"protected": protected_machine, "span": "json"})
        return (STATUS_PASS, None, "", {})'''
OLD_QUOTE_BRANCH = '''    unpaired = len(unpaired_positions)
    if not found and not unpaired:
        return (STATUS_PASS, None, "", {})'''

NEW_REPEAT_GUARD = '''    repeated = {str(row.get("phrase_sha12") or "") for row in sticky}
    repeated.discard("")
    if not repeated:
        return text, 0
'''
NEW_REPEAT_CHECK = '''    if not any(_sha12(gram) in repeated for gram in _ngrams(tail)):
        # Финальная фраза не содержит найденного повтора: удалять её нельзя
        # (это была бы потеря постороннего текста).
        return text, 0
    candidate = text[:start].rstrip()'''
OLD_REPEAT_CHECK = '''    tail_norm = _normalize_for_repeat(tail)
    if not any(gram in tail_norm for gram in _ngrams(tail)):
        return text, 0
    candidate = text[:start].rstrip()'''

NEW_REPEAT_DOC = '''    Снимается только ПОВТОРЯЮЩАЯСЯ финальная фраза (≥ ``PHRASE_MIN_WORDS``
    слов, вне защищённых сегментов), если ответ остаётся непустым. Суть ответа
    не переписывается: фраза, в которой НЕТ найденного повтора, не удаляется
    никогда (review-w3 F2) — хвост сверяется с фактическими находками по
    хешам n-грамм. Повтор не в хвосте → текст не трогаем (наблюдение)."""'''
OLD_REPEAT_DOC = '''    Снимается только ПОВТОРЯЮЩАЯСЯ финальная фраза (≥ ``PHRASE_MIN_WORDS``
    слов, вне защищённых сегментов), если ответ остаётся непустым. Суть ответа
    не переписывается."""'''

NEW_VERIFY_DOC = '''    Порядок: проход формы (до сериализации) → сериализация/escape ветки
    доставки → egress-guard (``sanitize_outgoing``) → проверка БЕЗ правок
    именно доставляемых байтов → отправка. Если hard-правило формы нарушено на
    payload, это видно в событии и в логе — «styled=true» при провале не
    объявляется. Ошибка проверки не роняет доставку (fail-open)."""'''
OLD_VERIFY_DOC = '''    Выполняется после сериализации (escape/parse_mode/снятие разметки) и без
    правок: если hard-правило формы нарушено на payload, это видно в событии и
    в логе — «styled=true» при провале не объявляется. Ошибка проверки не
    роняет доставку (fail-open)."""'''

NEW_LOOP_HEAD = '''        recheck_attempts = 0
        styled_text = None
        style_outcome = None
        while True:'''
OLD_LOOP_HEAD = '''        recheck_attempts = 0
        while True:'''

NEW_LOOP_HOOK = '''            # ── SOUL-1 (W3, SOUL-16.4.1 + SOUL-AMD.3.5, fix F4 review-w3):
            # ЕДИНСТВЕННАЯ точка применения прохода формы для инициативных
            # текстов — перед чанкованием и отправкой, поэтому проходят его И
            # writer-текст, И `prepared_text` (nostalgia): проверяется и
            # правится ровно то, что уйдёт. На один текст — один проход
            # (переоценка §18D может перегенерировать текст → проход заново).
            if str(prepared_text or "") != styled_text:
                prepared_text, style_outcome = await _style_initiative_text(
                    str(prepared_text or ""), chat_id, l1_plan)
                styled_text = str(prepared_text or "")
'''

NEW_WRITER_TAIL = '''        # ── SOUL-1 (W3, SOUL-16.4.1 + SOUL-AMD.3.5, fix F4 review-w3): проход
        # формы здесь НЕ выполняется — единственная точка применения для
        # инициативных текстов это `handle_initiative` (перед чанкованием и
        # отправкой), иначе ностальгия/`prepared_text` обходила бы проход, а
        # writer-текст проходил бы его дважды (SOUL-16.4.2 «один проход»).
        return prepared'''
OLD_WRITER_TAIL = '''        # ── SOUL-1 (W3, SOUL-16.4.1 + SOUL-AMD.3.5): те же правила формы, что в
        # Direct (инициатива — авторский текст того же Core). Единый проход,
        # контекст `initiative` (правила пакета инициативы + обычной речи).
        _style_outcome = await _style_policy.apply_style_policy(
            prepared, chat_id=chat_id, plan=response_plan,
            context="initiative", emit_events=True,
            stage="initiative_pre_send")
        if _style_outcome.applied and str(_style_outcome.text or ""):
            prepared = _style_outcome.text
        return prepared'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def revert_style() -> None:
    text = STYLE.read_text(encoding="utf-8")
    start = text.index("#: Пределы распознавания машинных данных")
    end = text.index("def segment(text: Any")
    text = text[:start] + OLD_JSON + "\n\n\n" + text[end:]
    start = text.index("def _merge_spans(")
    end = text.index("def protected_ranges(")
    text = text[:start] + OLD_MERGE + "\n\n\n" + text[end:]
    start = text.index("def _protected_machine_quotes(")
    end = text.index("def _apply_quotation_marks(")
    text = text[:start] + text[end:]
    assert NEW_QUOTE_BRANCH in text
    text = text.replace(NEW_QUOTE_BRANCH, OLD_QUOTE_BRANCH, 1)
    assert NEW_REPEAT_GUARD in text and NEW_REPEAT_CHECK in text
    text = text.replace(NEW_REPEAT_GUARD, "", 1)
    text = text.replace(NEW_REPEAT_CHECK, OLD_REPEAT_CHECK, 1)
    assert NEW_REPEAT_DOC in text
    text = text.replace(NEW_REPEAT_DOC, OLD_REPEAT_DOC, 1)
    STYLE.write_text(text, encoding="utf-8", newline="\n")


def revert_direct() -> None:
    text = DIRECT.read_text(encoding="utf-8")
    # F3: убрать post-guard хелпер и вернуть прежнюю проверку/докстринг.
    start = text.index("def _delivered_payload(payload: str) -> str:")
    end = text.index("def _verify_style_payload(")
    text = text[:start] + text[end:]
    assert NEW_VERIFY_DOC in text
    text = text.replace(NEW_VERIFY_DOC, OLD_VERIFY_DOC, 1)
    assert "        payload = _delivered_payload(payload)\n" in text
    text = text.replace("        payload = _delivered_payload(payload)\n", "", 1)
    # F4: убрать хелпер и хук в единой точке отправки, вернуть хук в writer.
    start = text.index("async def _style_initiative_text(")
    end = text.index("async def handle_initiative(")
    text = text[:start] + text[end:]
    assert "        evaluated_version = None\n        l1_plan = None\n" in text
    text = text.replace(
        "        evaluated_version = None\n        l1_plan = None\n",
        "        evaluated_version = None\n", 1)
    assert NEW_LOOP_HEAD in text and NEW_LOOP_HOOK in text
    text = text.replace(NEW_LOOP_HEAD, OLD_LOOP_HEAD, 1)
    text = text.replace(NEW_LOOP_HOOK, "", 1)
    assert NEW_WRITER_TAIL in text
    text = text.replace(NEW_WRITER_TAIL, OLD_WRITER_TAIL, 1)
    DIRECT.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    before = {"style": sha(STYLE), "direct": sha(DIRECT)}
    backups = {"style": SCRATCH / "_style_policy.fixed.bak",
               "direct": SCRATCH / "_direct_chat_service.fixed.bak"}
    shutil.copy2(STYLE, backups["style"])
    shutil.copy2(DIRECT, backups["direct"])
    revert_style()
    revert_direct()
    print("reverted sha:", sha(STYLE)[:12], sha(DIRECT)[:12])

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    python = str(ROOT / ".venv" / "Scripts" / "python.exe")
    for probe, out in (("_fix_probe_f1f2.py", "_fix_before-f1f2.txt"),
                       ("_fix_probe_f3f4.py", "_fix_before-f3f4.txt"),
                       ("_fix_probe_final.py", "_fix_before-final.txt")):
        proc = subprocess.run(
            [python, str(SCRATCH / "_fix_run.py"), str(SCRATCH / probe),
             str(SCRATCH / out)],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        print(probe, "exit=", proc.returncode)

    shutil.copy2(backups["style"], STYLE)
    shutil.copy2(backups["direct"], DIRECT)
    after = {"style": sha(STYLE), "direct": sha(DIRECT)}
    print("restored:", after["style"][:12], after["direct"][:12],
          "equal:", after == before)
    if after != before:
        raise SystemExit("ВОССТАНОВЛЕНИЕ НЕ СОВПАЛО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
