# -*- coding: utf-8 -*-
"""FIX-SPEECH-MOBILE — контракт явного входа «Речь и характер» на хабе «ИИ».

Живой дефект владельца (18.10): на мобильном раздел «Речь и характер»
отсутствовал — «её просто нет: ни в одном разделе, ни в модулях, ни в
разделе ИИ». По коду экран `#/ai/speech` и вход в persona-табе были, но на
хабе «ИИ» не было ни одной двери с этим именем.

Контракт этого фикса (директива владельца §6.3, навигация НЕ переделывается):

* на хабе «ИИ» есть явная строка-вход `[data-speech-hub-entry]`, ведущая на
  существующий маршрут `#/ai/speech`;
* состав карточек хаба «ИИ» не меняется — ровно 5 страниц (`HUBS_V2`);
* права входа — существующие (`canViewTab('speech')`), второй вход в
  persona-табе сохраняется;
* поверхность входа не заявлена как стеклянная (не тянет Tier A и не
  участвует в glass-селекторе поверхностей).

TEST-LIFECYCLE: CONTRACT owner=FIX-SPEECH-MOBILE (§6.3 мобильный путь
«Ещё» → «ИИ»; полный список редакторов доступен на узком экране);
REGRESSION owner=FIX-SPEECH-MOBILE (18.10: двери «Речи и характера» на
хабе «ИИ» не было).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


def _hub_v2_ai_block() -> str:
    return APP_JS[APP_JS.index("var HUBS_V2 = {"):
                  APP_JS.index("'#/memory': {")]


def test_hub_has_explicit_speech_entry():
    assert "data-speech-hub-entry" in INDEX
    assert "hubSpeechEntry" in APP_JS
    # Клик ведёт на существующий маршрут (никаких новых экранов).
    entry_html = INDEX[INDEX.index("data-speech-hub-entry"):
                       INDEX.index("data-speech-hub-entry") + 400]
    assert "navigateTo('#/ai/speech')" in entry_html
    assert "Речь и характер" in entry_html


def test_entry_gated_by_existing_speech_permission():
    fn = APP_JS[APP_JS.index("hubSpeechEntry: function () {"):]
    fn = fn[:fn.index("},")]
    assert "this.route === '#/ai'" in fn
    assert "this.canViewTab('speech')" in fn


def test_navigation_untouched_five_hub_pages():
    # L-F11S-1: «5 страниц хаба» исторически менялось дважды и НЕ является
    # целью само по себе: EVOL-031 убрал «Умный кэш» (5→4), EVOL-028 v0.8 убрал
    # дублирующий пункт «Личность и стиль» (4→3) — личность редактируется в
    # единственном каноническом редакторе «Речь и характер»
    # (plans/current_task.md L402). Инвариант W6 сохранён: вход в «Речь и
    # характер» — отдельная строка-дверь на том же экране, а не новая карточка.
    hub = _hub_v2_ai_block()
    assert hub.count("route: '#/ai/") == 3
    assert "tab: 'persona'" not in hub


def test_persona_entry_still_present():
    # L-F11S-1 (EVOL-028 v0.8, W10): второй двери `data-speech-entry` больше
    # нет — она жила в отдельном экране «Личность и стиль», который удалён
    # вместе с дублирующей навигацией. Вход остался один (строка хаба), а
    # старый адрес `#/ai/persona` стал deep-link'ом в секцию личности того же
    # канонического редактора.
    assert "data-speech-entry" not in INDEX
    assert "data-speech-hub-entry" in INDEX
    area = INDEX[INDEX.index("data-speech-hub-entry"):
                 INDEX.index("data-speech-hub-entry") + 400]
    assert "navigateTo('#/ai/speech')" in area
    assert "Речь и характер" in area


def test_entry_surface_is_not_glass_and_has_touch_target():
    assert ".speech-hub-entry" in CSS
    block = CSS[CSS.index("FIX-SPEECH-MOBILE (18.10"):]
    block = block[:block.index("/* ═══ /FIX-SPEECH-MOBILE ═══ */")]
    assert "min-height: 56px" in block
    assert "grid-column: 1 / -1" in block
    # Не тянем glass-поверхности этим блоком.
    for forbidden in ("backdrop-filter", "data-glass", "#lg-lens",
                      "polygon-background"):
        assert forbidden not in block, forbidden


def test_hub_entry_glyph_is_in_subset():
    # REFINE рядом с правкой: record_voice_over отсутствует в ICONS (пустой
    # значок); у дверей «Речи и характера» стоит глиф из сабсета.
    entry_html = INDEX[INDEX.index("data-speech-hub-entry"):
                       INDEX.index("data-speech-hub-entry") + 400]
    assert "iconGlyph('record_voice_over')" not in entry_html
    assert "iconGlyph('edit_note')" in entry_html
    assert "edit_note:" in APP_JS
