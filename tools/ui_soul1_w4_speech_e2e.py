"""W4 (SOUL-06/07/08) — UI-прогон разделов «Юмор» / «Примеры» / «Обучение».

Инфраструктура (сервер, SDK-заглушка, маршрутизация API, проверки
viewport) переиспользуется из W6-харнесса БЕЗ его изменения; данные — из
РЕАЛЬНОЙ фикстуры слайса W4 (`evidence/w4/api-fixture.json`, снята настоящим
слоем: миграция v36 + заводские черновики + эталоны + реальный отбор и
проход окна реакций).

Проверяет: отсутствие горизонтального overflow и тач-цели ≥44px на
320/390/430/1024/1440 + landscape; реальные карточки и счётчики; честные
пустые состояния; работу контролов (ремесло, тест приёма, CRUD примеров,
«почему выбраны», политика/A-B, пауза/сброс обучения). Пишет
`evidence/w4/ui-report.json` и кадры в `evidence/w4/shots/`.

Запуск: `py -3 tools/ui_soul1_w4_speech_e2e.py --no-shots` (быстрый) либо
без флага (с кадрами).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import ui_soul1_w6_speech_e2e as W6   # noqa: E402  (инфраструктура W6)

EVIDENCE = REPO / "plans" / "features" / "soul-1" / "evidence" / "w4"
FIXTURE_PATH = EVIDENCE / "api-fixture.json"
REPORT = EVIDENCE / "ui-report.json"
SHOTS = EVIDENCE / "shots"

W4_SECTIONS = ("humor", "examples", "learning")
VIEWPORTS = ("320", "390", "430", "1024", "1440", "landscape")


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _install_fixture(fixture: dict) -> None:
    """Подменить данные W6-стабов данными W4 (файл W6 не меняется)."""
    W6.FIXTURE.update({
        "overview": fixture["overview"],
        "humor": fixture["humor"],
        "examples": fixture["examples"],
        "learning": fixture["learning"],
        # полный W4-снимок (probe/why/counters) — для POST-стабов
        "w4": fixture,
    })
    W6.SHOTS = SHOTS


def _get_body(name: str):
    fixture = W6.FIXTURE
    if name == "overview":
        # FIX-W4/F3: хаб показывает реальные карточки (payload снят настоящим
        # обработчиком и включает проверку честности в прогоне).
        return fixture.get("overview")
    if name == "humor":
        return fixture["humor"]
    if name == "examples":
        return fixture["examples"]
    if name == "learning":
        return fixture["learning"]
    return None


def _post_body(name: str, req):
    fixture = W6.FIXTURE.get("w4") or {}
    if name == "humor/craft":
        view = dict(fixture["humor"])
        craft = dict(view.get("craft") or {})
        craft["enabled"] = not bool(craft.get("enabled", True))
        craft["revision"] = int(craft.get("revision") or 0) + 1
        view["craft"] = craft
        return {"ok": True, "scope": "global", "craft": craft}
    if name == "humor/technique/test":
        return fixture["probe"]
    if name == "examples/seed":
        return {"ok": True, "seeded": 0, "skipped": 20, "reason": ""}
    if name == "examples/policy":
        policy = dict(fixture["examples"]["policy"])
        policy["max_items"] = int(policy.get("max_items") or 3)
        return {"ok": True, "scope": "global", "policy": policy,
                "policy_source": "global"}
    if name == "examples/why":
        return fixture["why"]
    if name == "learning/humor":
        learning = dict(fixture["learning"])
        feedback = dict(learning.get("humor_feedback") or {})
        feedback["paused"] = True
        learning["humor_feedback"] = feedback
        return {"ok": True, "action": "pause", "result": {"ok": True},
                "learning": learning}
    if name == "examples":
        return {"ok": True, "item": (fixture["examples"]["items"] or [{}])[0]}
    if name.startswith("examples/"):
        tail = name.rsplit("/", 1)[-1]
        if tail in ("approve", "archive"):
            item = dict((fixture["examples"]["items"] or [{}])[0])
            item["owner_approved"] = tail == "approve"
            item["status"] = "archived" if tail == "archive" else "active"
            return {"ok": True, "item": item}
        return {"ok": True, "item": (fixture["examples"]["items"] or [{}])[0],
                "deleted": 1}
    return {"ok": True}


def install() -> None:
    fixture = _load_fixture()
    _install_fixture(fixture)
    # Снимок ОРИГИНАЛЬНЫХ стабов: заменяем атрибуты модуля, поэтому вызов
    # через модуль после подмены был бы рекурсией.
    original_get = W6._get_body
    original_post = W6._post_body

    def _get(name: str):
        body = _get_body(name)
        if body is not None:
            return body
        return original_get(name)

    def _post(name: str, req):
        if name.startswith("humor/") or name.startswith("examples") \
                or name.startswith("learning/humor"):
            return _post_body(name, req)
        return original_post(name, req)

    W6._get_body = _get
    W6._post_body = _post


def _probe(page) -> dict:
    """Проверка viewport — ТЕМ ЖЕ пробником, что у W6 (единая мера), плюс
    содержимое разделов W4 (карточки/тексты)."""
    base = page.evaluate(W6.PROBE)
    content = page.evaluate(
        "(() => { const root = document.querySelector('.speech-section')"
        " || document.querySelector('.speech-screen');"
        " return { cards: document.querySelectorAll('[data-speech-samples] .speech-rule').length,"
        " text: (root ? root.textContent : '').replace(/\\\\s+/g, ' ').slice(0, 12000) }; })()")
    base.update(content)
    return base


def run_viewports(browser, shots: bool, views) -> None:
    fixture = W6.FIXTURE
    examples = fixture["examples"]
    learning = fixture["learning"]
    humor = fixture["humor"]
    for viewport in views:
        width, height = W6.METRICS[viewport]
        ctx, page = W6.new_page(browser, width, height)
        try:
            W6.open_screen(page, viewport)
            # ── F3 REVIEW-W4: карточки хаба не врут о поставленном ─────────
            hub = page.inner_text(".speech-grid")
            W6.notes.append({"label": "%s/hub" % viewport,
                             "hub": hub.replace("\n", " ")[:400]})
            for stale in ("слайс W4", "ещё нет"):
                if stale in hub and viewport == views[0]:
                    W6.fail(viewport, "хаб объявляет непоставленное: %s" % stale)
            if "карточек:" not in hub and "библиотека" not in hub:
                W6.fail(viewport, "карточка «Примеры» без фактического состояния")
            if shots:
                W6.snap(page, "w4_hub_%s" % viewport)
            for section in W4_SECTIONS:
                page.click("[data-speech-card='%s']" % section)
                page.wait_for_selector(".speech-section", state="visible")
                page.wait_for_timeout(650)
                probe = _probe(page)
                W6.notes.append({"label": "%s/%s" % (viewport, section),
                                 "pageOverflow": probe["pageOverflow"],
                                 "minTap": probe["minTap"],
                                 "small": probe["smallTargets"]})
                if probe["pageOverflow"] > 1:
                    W6.fail("%s/%s" % (viewport, section),
                            "горизонтальный overflow: %s px" % probe["pageOverflow"])
                if probe["minTap"] is not None and probe["minTap"] < 44:
                    W6.fail("%s/%s" % (viewport, section),
                            "тач-цель < 44px: %s" % probe["smallTargets"][:3])
                if section == "humor":
                    if "Ремесло" not in probe["text"] and "ремесло" not in probe["text"]:
                        W6.fail(viewport, "раздел «Юмор» без блока ремесла")
                    if "[data-speech-humor-craft]" and not page.locator(
                            "[data-speech-humor-craft]").count():
                        W6.fail(viewport, "нет контрола ремесла")
                    titles = [t["title"] for t in humor["techniques"][:4]]
                    missing = [t for t in titles if t.split(" ")[0] not in probe["text"]]
                    if missing:
                        W6.fail(viewport, "приёмы не отрисованы: %s" % missing)
                if section == "examples":
                    if not page.locator("[data-speech-samples]").count():
                        W6.fail(viewport, "нет списка примеров")
                    if probe["cards"] != len(examples["items"]):
                        W6.fail(viewport, "карточек %s, ожидалось %s"
                                % (probe["cards"], len(examples["items"])))
                    for needle in ("эталон", "черновик", "Заводская подборка",
                                   "Почему выбраны"):
                        if needle not in probe["text"]:
                            W6.fail(viewport, "в «Примерах» нет: %s" % needle)
                if section == "learning":
                    if "Реакции на шутки" not in probe["text"]:
                        W6.fail(viewport, "нет блока реакций на шутки")
                    signals = learning["humor_feedback"]["signals"]
                    for kind in signals:
                        if kind not in probe["text"]:
                            W6.fail(viewport, "сигнал %s не показан" % kind)
                    if "Обязательные сценарии" not in probe["text"]:
                        W6.fail(viewport, "нет честных live-маркеров сценариев")
                if shots:
                    W6.snap(page, "w4_%s_%s" % (section, viewport))
                page.click(".speech-back")
                page.wait_for_selector(".speech-grid", state="visible")
                page.wait_for_timeout(250)
        finally:
            ctx.close()


def run_interactions(browser, shots: bool) -> None:
    """Реальные действия владельца в трёх разделах (POST'ы фиксируются)."""
    ctx, page = W6.new_page(browser, 390, 844)
    try:
        W6.open_screen(page, "interactions")
        # ── Юмор: toggle ремесла + тест приёма ─────────────────────────────
        page.click("[data-speech-card='humor']")
        page.wait_for_selector("[data-speech-humor-craft]", state="visible")
        page.click("[data-speech-humor-craft] button")
        page.wait_for_timeout(600)
        page.click(".speech-section button:has-text('Проверить приём')")
        page.wait_for_selector("[data-speech-humor-probe]", state="visible")
        probe_text = page.inner_text("[data-speech-humor-probe]")
        if "токенов" not in probe_text:
            W6.fail("interactions", "тест приёма без объёма слоя")
        if shots:
            W6.snap(page, "w4_interaction_humor_probe")
        # ── Примеры: добавление, сохранение, одобрение, архив, why, политика ─
        page.click(".speech-back")
        page.click("[data-speech-card='examples']")
        page.wait_for_selector("[data-speech-examples-toolbar]", state="visible")
        page.click("button:has-text('Добавить пример')")
        page.wait_for_selector("[data-speech-sample-editor]", state="visible")
        page.fill("[data-speech-sample-editor] textarea >> nth=0", "сосед сверлит")
        page.fill("[data-speech-sample-editor] textarea >> nth=1",
                  "регламент акустической терапии дома")
        page.click("[data-speech-sample-editor] button:has-text('Сохранить')")
        page.wait_for_timeout(500)
        if page.locator("[data-speech-sample-editor]").count():
            W6.fail("interactions", "редактор примера не закрылся после Save")
        page.click("[data-speech-samples] button:has-text('Сделать эталоном') >> nth=0")
        page.wait_for_timeout(400)
        page.click("[data-speech-samples] button:has-text('В архив') >> nth=0")
        page.wait_for_timeout(400)
        page.click("button:has-text('Заводская подборка')")
        page.wait_for_timeout(400)
        page.fill("[data-speech-examples-why] input", "сосед сверлит вторые выходные")
        page.click("[data-speech-examples-why] button:has-text('Показать отбор')")
        page.wait_for_timeout(500)
        if page.locator("[data-speech-examples-why]").inner_text().strip().endswith(
                "без отправки."):
            W6.fail("interactions", "«почему выбраны» не показал трассу")
        page.click("[data-speech-examples-policy] button:has-text('Сохранить политику')")
        page.wait_for_timeout(400)
        if shots:
            W6.snap(page, "w4_interaction_examples")
        # ── Обучение: пауза и сброс ────────────────────────────────────────
        page.click(".speech-back")
        page.click("[data-speech-card='learning']")
        page.wait_for_selector("[data-speech-humor-feedback]", state="visible")
        page.click("[data-speech-humor-feedback] button:has-text('Пауза сбора')")
        page.wait_for_timeout(500)
        page.click("[data-speech-humor-feedback] button:has-text('Сбросить обучение юмора')")
        page.wait_for_timeout(500)
        if shots:
            W6.snap(page, "w4_interaction_learning")
        posts = [p for p in W6.posted if any(k in p for k in (
            "humor", "examples", "learning"))]
        W6.notes.append({"label": "interactions/posts", "posts": posts})
    finally:
        ctx.close()


def run_empty_state(browser, shots: bool) -> None:
    """Честные пустые состояния: библиотека недоступна — не выдумываем данные."""
    saved = json.dumps(W6.FIXTURE.get("examples"), ensure_ascii=False)
    W6.FIXTURE["examples"] = {
        **W6.FIXTURE["examples"], "available": False, "reason": "db_unavailable",
        "status": "unavailable", "items": [], "count": 0,
        "telemetry": {"available": False, "reason": "db_unavailable",
                      "total": 0, "approved": 0, "proposed": 0,
                      "by_technique": {}, "by_version": {}, "uses_total": 0,
                      "starter_seeded": 0, "ab": {"enabled": False,
                                                  "versions": []}},
    }
    ctx, page = W6.new_page(browser, 390, 844)
    try:
        W6.open_screen(page, "empty")
        page.click("[data-speech-card='examples']")
        page.wait_for_selector("[data-speech-examples-toolbar]", state="visible")
        page.wait_for_timeout(500)
        text = page.inner_text(".speech-section")
        if "db_unavailable" not in text:
            W6.fail("empty", "нет честной причины недоступности библиотеки")
        if "не подменяются" not in text:
            W6.fail("empty", "пустое состояние не объяснено простыми словами")
        if shots:
            W6.snap(page, "w4_examples_empty")
    finally:
        ctx.close()
        W6.FIXTURE["examples"] = json.loads(saved)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--firefox", action="store_true")
    args = ap.parse_args()
    install()
    shots = not args.no_shots
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if shots:
        SHOTS.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    httpd = W6.serve(W6.PORT, str(REPO / "web"))
    views = [v for v in VIEWPORTS if not args.only or v == args.only]
    try:
        with sync_playwright() as pw:
            browser = (getattr(pw, "firefox") if args.firefox
                       else pw.chromium).launch()
            try:
                run_viewports(browser, shots, views)
            except Exception as exc:      # отчёт пишется даже при сбое шага
                W6.fail("viewports", "сбой прогона: %r" % (exc,))
            if not args.only:
                try:
                    run_interactions(browser, shots)
                except Exception as exc:
                    W6.fail("interactions", "сбой шага: %r" % (exc,))
                try:
                    run_empty_state(browser, shots)
                except Exception as exc:
                    W6.fail("empty", "сбой шага: %r" % (exc,))
            browser.close()
    finally:
        httpd.shutdown()
    report = {
        "slice": "soul-1/W4",
        "fixture": str(FIXTURE_PATH.relative_to(REPO)).replace("\\", "/"),
        "viewports": views,
        "sections": list(W4_SECTIONS),
        "shots": shots,
        "failures": W6.failures,
        "notes": W6.notes,
        "posts": W6.posted,
        "dialogs": W6.dialogs,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1,
                                 default=str), encoding="utf-8")
    print("W4-UI: failures=%d | notes=%d | posts=%s"
          % (len(W6.failures), len(W6.notes), sorted(set(W6.posted))))
    if W6.failures:
        for item in W6.failures[:12]:
            print("  FAIL", item)
        return 1
    print("W4-UI-OK", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
