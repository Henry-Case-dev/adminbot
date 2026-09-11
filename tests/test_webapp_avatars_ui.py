"""UI-полировка TMA — статический аудит бэкенда и фронта аватаров.

Бэкенд (grep по коду): runtime-держатель Bot (services/web_runtime.py +
вызов в bot.py перед create_app), /api/me (last_name/photo_url), прокси
GET /api/avatar/{kind}/{tid} (web/api/avatars.py: chat big_file_id / user
get_user_profile_photos, download в BytesIO, image/jpeg + Cache-Control
max-age=86400, RAM-TTL-кэш 1ч/500 записей, 404 на ошибки), включение
router в web/app.py и обогащение /api/chat_lore (title/photo_file_id чата
и username/photo_file_id участников — только топ-50; остальным None — фронт
догружает лениво с стаггером 300мс, Hotfix-R10). Негативы
обогащения (ошибка Bot API / нет фото) тоже пишутся в RAM-кэш
(fix-раунд: chat_display_info/user_display_info не долбят Bot API).

Фронт (web/app.js + web/index.html) — fix-раунд ревью: прямые
<img src="/api/avatar/..."> ЗАПРЕЩЕНЫ (браузер грузит картинку БЕЗ
X-Telegram-Init-Data → 401). Метод avatarUrl(kind, id) — fetch прокси
с заголовком initData → blob → URL.createObjectURL → кэш Map (лимит
~200, revoke старых), null на 401/404; loadAvatar кладёт URL в
реактивное поле (chat.avatarUrl/u.avatarUrl), img рисуется только через
v-if="…photo_file_id != null && ….avatarUrl" (photo_file_id==null — img
не рисуем вовсе); @error — сброс поля (avatarError/onMeAvatarError),
НЕ style.display (после него img не появился бы при ре-рендере). Шапка:
CDN me.photo_url сразу, при onerror — фолбек на прокси
(avatarUrl('user', me.telegram_id)). JS-тестов нет — аудируем маркеры
(образец test_webapp_lore_ui.py / test_webapp_agi_ui.py).
"""
import re


class _Static:
    @staticmethod
    def read(path):
        return open(path, encoding="utf-8").read()

    @staticmethod
    def body(src, method_name):
        """Тело метода (по имени, включая 'async function') до конца."""
        # 10.7: имя может встречаться и как поле объекта (напр. `avatarUrl:`
        # внутри scopeOptions) — ищем именно определение функции.
        match = re.search(
            r"(?m)^[ \t]*" + re.escape(method_name)
            + r":[ \t]*(?:async[ \t]+)?function", src)
        start = match.start() if match else src.index(method_name + ":")
        end = src.index("\n      },", start)
        return src[start:end]

    @staticmethod
    def has_method(src, name):
        return re.search(name + r":\s*(async\s+)?function", src) is not None


# ═══ Бэкенд: runtime + /me + аватар-прокси + обогащение ═════════════════════

class TestAvatarBackendAudit:
    def test_web_runtime_holder_exists(self):
        src = _Static.read("services/web_runtime.py")
        for marker in ("def set_web_bot(bot)", "def get_web_bot()",
                       "def reset_web_runtime()", "_bot = None"):
            assert marker in src, f"нет маркера {marker}"

    def test_bot_wires_bot_before_create_app(self):
        """bot.py: set_web_bot(bot) вызывается ДО create_app (web-api видит
        бота уже при старте uvicorn)."""
        src = _Static.read("bot.py")
        assert "from services.web_runtime import set_web_bot" in src
        assert src.index("set_web_bot(bot)") < src.index(
            "app = create_app(cache, control=control)")

    def test_me_route_carries_last_name_and_photo_url(self):
        src = _Static.read("web/api/routes.py")
        assert '"last_name": user.last_name' in src
        assert '"photo_url": user.photo_url' in src

    def test_avatar_route_declared(self):
        src = _Static.read("web/api/avatars.py")
        assert "@avatar_router.get(\"/avatar/{kind}/{tid}\")" in src
        assert 'Literal["chat", "user"]' in src
        assert "Depends(get_tma_user)" in src

    def test_avatar_chat_and_user_file_ids(self):
        """chat → get_chat().photo.big_file_id; user → getUserProfilePhotos
        limit=1 (без скачивания на этом шаге)."""
        src = _Static.read("web/api/avatars.py")
        assert "bot.get_chat(tid)" in src
        assert "big_file_id" in src
        assert "bot.get_user_profile_photos(tid, limit=1)" in src

    def test_avatar_download_to_memory_and_response(self):
        src = _Static.read("web/api/avatars.py")
        assert "bot.get_file(" in src
        assert "io.BytesIO()" in src
        assert "media_type=\"image/jpeg\"" in src
        assert "Cache-Control" in src
        assert "public, max-age=86400" in src

    def test_avatar_ram_ttl_cache_constants(self):
        src = _Static.read("web/api/avatars.py")
        assert "_TTL_SECONDS = 3600" in src
        assert "_MAX_CACHE_ENTRIES = 500" in src
        assert "dict[tuple[str, int], tuple[float, bytes | None]]" in src

    def test_avatar_errors_are_404(self):
        src = _Static.read("web/api/avatars.py")
        assert "raise HTTPException(status_code=404" in src
        assert 'detail="avatar not found"' in src

    def test_avatar_transient_errors_not_negative_cached(self):
        """BUG-4 (рекон раунда 10): rate-limit/сетевые ошибки Bot API
        (TelegramRetryAfter/TelegramNetworkError) — возврат None БЕЗ записи
        негатива в кэш (иначе пустые аватары висят час); негатив кэшируется
        только при дефинитивном «нет фото» (пустой list/file_id)."""
        src = _Static.read("web/api/avatars.py")
        assert "from aiogram.exceptions import TelegramNetworkError, " \
            "TelegramRetryAfter" in src
        seg = src.split("async def fetch_avatar_bytes")[1]
        seg = seg.split("async def chat_display_info")[0]
        assert "except (TelegramRetryAfter, TelegramNetworkError)" in seg
        assert "NOT cached" in seg
        assert seg.index("return None") < seg.index("_cache_put")
        assert "_cache_put(_avatar_cache, key, data)" in seg

    def test_avatar_router_included_in_app(self):
        src = _Static.read("web/app.py")
        assert "from web.api.avatars import avatar_router" in src
        assert "app.include_router(avatar_router, prefix=\"/api\")" in src

    def test_chat_lore_chats_enriched_title_photo(self):
        src = _Static.read("web/api/chat_lore.py")
        assert "from web.api.avatars import chat_display_info" in src
        assert "chat_display_info(p.chat_id)" in src
        assert '"title": info["title"]' in src
        assert '"photo_file_id": info["photo_file_id"]' in src

    def test_relations_enrich_all_rows_username_photo_top50(self):
        """Раунд 10.4 (H-2): username — ВСЕМ строкам (Semaphore(5), кэш 1ч);
        photo_file_id — только первые _RELATIONS_ENRICH_TOP (фронт догружает
        лениво со стаггером — loadRelationAvatarsLazy)."""
        src = _Static.read("web/api/chat_lore.py")
        assert "_RELATIONS_ENRICH_TOP = 50" in src
        assert "_RELATIONS_SEMAPHORE_LIMIT = 5" in src
        assert "asyncio.Semaphore(_RELATIONS_SEMAPHORE_LIMIT)" in src
        assert "await asyncio.gather" in src
        assert "user_display_info(chat_id, uid)" in src
        assert "[:_RELATIONS_ENRICH_TOP]" in src
        assert 'u["photo_file_id"] = None' in src

    def test_user_display_info_uses_cached_bot_api(self):
        src = _Static.read("web/api/avatars.py")
        assert "bot.get_chat_member(chat_id, user_id)" in src
        assert "get_user_profile_photos(user_id, limit=1)" in src
        assert "get_web_bot()" in src

    def test_relations_alias_resolver_unconditional(self):
        """Hotfix-R10 (имена = raw-ID): chat_lore.py строит AliasResolver
        напрямую из hot-кэша — НЕ через RelationsService.aliases (тот
        гейтится flags.summary_enabled в bot.py); при выключенном саммари
        имена участников остаются alias → username → name-map.
        Раунд 10.2: чистки имён нет вообще (_clean_nickname удалён —
        эмодзи/спецсимволы как есть); @-снятие с username сохранено; id
        как имя удаляется (del u['name'])."""
        src = _Static.read("web/api/chat_lore.py")
        assert "from services.summary_aliases import AliasResolver" in src
        # Раунд 10.4 (B-13): per-chat резолв алиасов (override чата →
        # глобальные; fail-open), напрямую — НЕ через RelationsService
        assert "build_alias_resolver(chat_id)" in src
        assert "alias_resolver.resolve(uid, None, None)" in src
        assert 'u["name"] = tidy_name' in src
        assert "_clean_nickname" not in src
        assert 'del u["name"]' in src
        assert 'u["username"]).lstrip("@"' in src or '.lstrip("@")' in src
        assert "alias → nickname (name-map" in src

    # ══ fix-раунд: негатив-кэш обогащения (ошибки тоже пишутся в кэш) ══

    def test_chat_info_error_is_cached_negative(self):
        """chat_display_info: except Bot API-ошибки → в кэш пишется пустой
        словарь (None-поля), а НЕ только успех — обогащение не долбит
        Bot API каждый запрос списка чатов."""
        src = _Static.read("web/api/avatars.py")
        seg = src.split("async def chat_display_info")[1]
        seg = seg.split("async def user_display_info")[0]
        put = "_cache_put(_chat_info_cache, chat_id, dict(info))"
        assert "except Exception:" in seg
        assert put in seg
        assert seg.index("except Exception:") < seg.index(put)

    def test_user_info_errors_are_cached_negative(self):
        """user_display_info: и get_chat_member, и getUserProfilePhotos при
        ошибке кэшируют None (негатив) — повторные relations-запросы не
        бьют в Bot API."""
        src = _Static.read("web/api/avatars.py")
        seg = src.split("async def user_display_info")[1]
        seg = seg.split("# ── роут")[0]
        puts = ("_cache_put(_username_cache, ukey, username)",
                "_cache_put(_user_photo_cache, user_id, photo_file_id)")
        excs = seg.count("except Exception:")
        assert excs >= 2
        for put in puts:
            assert put in seg
            assert seg.index("except Exception:") < seg.index(put)


# ═══ Фронт: app.js ═════════════════════════════════════════════════════════

class TestAvatarFrontAudit:
    def test_load_chats_defaults_title(self):
        """loadChats: серверный title может быть null (нет бота/ошибка) —
        подставляем 'Чат <id>', селектор не пустует."""
        body = _Static.body(_Static.read("web/app.js"), "loadChats")
        assert "!c.title" in body
        assert "c.title = 'Чат ' + c.chat_id" in body

    def test_no_close_app_method(self):
        """F-13 (AC-2): метод closeApp удалён (крестик ✕ принудительного
        закрытия Mini App убран из шапки; в Telegram закрытие штатное)."""
        src = _Static.read("web/app.js")
        assert not _Static.has_method(src, "closeApp")
        assert "closeApp" not in src
        assert _Static.has_method(src, "toggleFullscreen")

    def test_toggle_fullscreen_method(self):
        src = _Static.read("web/app.js")
        assert _Static.has_method(src, "toggleFullscreen")
        body = _Static.body(src, "toggleFullscreen")
        assert "Telegram.WebApp" in body
        assert "wa.requestFullscreen" in body
        assert "wa.exitFullscreen" in body
        assert "this.isFullscreen = !this.isFullscreen" in body

    def test_resolve_relation_name_no_id_fallback(self):
        """Раунд 10.2: resolveRelationName — alias → name → username (без
        @); user_id как имя — НИКОГДА (пустая строка; id в карточке и так
        мелким рядом)."""
        src = _Static.read("web/app.js")
        body = _Static.body(src, "resolveRelationName")
        assert "if (u.name) return String(u.name);" in body
        assert "if (u.username) return String(u.username);" in body
        assert "return '';" in body
        assert "return String(u.user_id);" not in body
        assert "aliases[String(u.user_id)]" in body  # мапа ключу по id — ок

    def test_avatar_initial_first_grapheme(self):
        """overflow-marker: Array.from(name)[0] — первая ГРАФЕМА (эмодзи/
        суррогатные пары не дают половинку; charAt(0) не используется)."""
        src = _Static.read("web/app.js")
        body = _Static.body(src, "avatarInitial")
        assert "Array.from(name)[0]" in body
        assert "name.charAt(0)" not in body

    # ══ fix-раунд: blob-аватары (avatarUrl + v-if + @error-сброс) ══

    def test_avatar_url_blob_fetch_with_init_data_header(self):
        """avatarUrl(kind,id): fetch /api/avatar/{kind}/{id} с заголовком
        X-Telegram-Init-Data → blob → URL.createObjectURL (НЕ через api() и
        НЕ через прямой <img src>: браузерная загрузка без заголовка
        получала 401)."""
        src = _Static.read("web/app.js")
        assert _Static.has_method(src, "avatarUrl")
        body = _Static.body(src, "avatarUrl")
        assert "fetch('/api/avatar/' + kind + '/' + id" in body
        assert "'X-Telegram-Init-Data'" in body
        assert "window.Telegram && Telegram.WebApp" in body
        assert "resp.blob()" in body
        assert "URL.createObjectURL" in body

    def test_avatar_url_cache_with_limit_and_revoke(self):
        """Кэш blob-URL: Map {kind:id → objectURL} (модульный _avatarCache);
        лимит ~200 (метка _AVATAR_CACHE_MAX = 200) — при переполнении
        revokeObjectURL самого старого."""
        src = _Static.read("web/app.js")
        assert "var _avatarCache = new Map()" in src
        assert "_AVATAR_CACHE_MAX = 200" in src
        body = _Static.body(src, "avatarUrl")
        assert "_avatarCache.set(key, url)" in body
        assert "_avatarCache.size > _AVATAR_CACHE_MAX" in body
        assert "URL.revokeObjectURL(oldUrl)" in body

    def test_avatar_url_null_on_error(self):
        """Ошибка сети/401/404 → null (без исключения): img по v-if просто
        не показывается; негатив в кэш НЕ пишем — повторный рендер
        (avatarUrl вызывается снова при загрузке списка) сможет сходить
        ещё раз."""
        body = _Static.body(_Static.read("web/app.js"), "avatarUrl")
        assert "if (!resp.ok) return null;" in body
        assert "return null;" in body

    def test_load_avatar_sets_reactive_field(self):
        """loadAvatar(kind,id,obj): async avatarUrl → кладёт URL в
        реактивное поле obj.avatarUrl (chat.avatarUrl / u.avatarUrl)."""
        src = _Static.read("web/app.js")
        assert _Static.has_method(src, "loadAvatar")
        body = _Static.body(src, "loadAvatar")
        assert "this.avatarUrl(kind, id)" in body
        assert "obj.avatarUrl = url" in body

    def test_header_avatar_cdn_then_proxy(self):
        """Шапка (fix-раунд): meAvatarUrl — CDN me.photo_url сразу; при
        отсутствии photo_url — blob avatarUrl('user', telegram_id);
        onerror CDN → фолбек на прокси (вторая попытка)."""
        src = _Static.read("web/app.js")
        assert _Static.has_method(src, "refreshMeAvatar")
        body = _Static.body(src, "refreshMeAvatar")
        assert "this.meAvatarUrl = ''" in body
        assert "me.photo_url" in body
        assert "loadAvatar('user', me.telegram_id)" in body
        err = _Static.body(src, "onMeAvatarError")
        assert "me.photo_url" in err
        assert "loadAvatar('user', me.telegram_id)" in err
        assert "this.meAvatarUrl = ''" in err

    def test_avatar_error_reset_method(self):
        """@error аватаров списков → avatarError(obj): сброс поля
        (obj.avatarUrl = null) — v-if убирает битый img; при следующей
        загрузке списка loadAvatar выставит URL снова (ре-рендер может
        показать аватар)."""
        src = _Static.read("web/app.js")
        assert _Static.has_method(src, "avatarError")
        body = _Static.body(src, "avatarError")
        assert "obj.avatarUrl = null" in body

    def test_lists_load_avatars_after_fetch(self):
        """loadChats/loadRelations: после получения списка вызывают
        loadAvatar для строк с photo_file_id != null (blob-URL в реактивное
        поле); для photo_file_id == null прокси НЕ запрашиваем вовсе.
        Hotfix-R10: loadRelations дополнительно вызывает ленивый догруз
        loadRelationAvatarsLazy (стаггер 300мс; негатив → avatarSkipped)."""
        src = _Static.read("web/app.js")
        assert _Static.has_method(src, "loadRelationAvatarsLazy")
        lazy = _Static.body(src, "loadRelationAvatarsLazy")
        assert "* 300" in lazy
        assert "avatarSkipped" in lazy
        assert "self.loadAvatar('user', u.user_id, u)" in lazy
        body = _Static.body(src, "loadChats")
        assert "c.photo_file_id != null" in body
        assert "self.loadAvatar('chat', c.chat_id, c)" in body
        body = _Static.body(src, "loadRelations")
        assert "u.photo_file_id != null" in body
        assert "self.loadAvatar('user', u.user_id, u)" in body
        assert "this.loadRelationAvatarsLazy(rows)" in body

    # ══ fix-раунд: index.html — v-if + @error вместо прямых src ══

    def test_no_direct_avatar_img_src(self):
        """Прямых <img src="/api/avatar/..."> НЕТ: такие src грузились бы
        браузером без X-Telegram-Init-Data → 401 (БЛОКЕР fix-раунда)."""
        html = _Static.read("web/index.html")
        assert ':src="\'/api/avatar' not in html
        assert 'src="/api/avatar' not in html

    def test_no_display_none_mechanics(self):
        """onerror больше НЕ прячет img через style.display='none' (после
        display:none img не появился бы при ре-рендере) — только v-if +
        @error-сброс поля."""
        html = _Static.read("web/index.html")
        assert "style.display" not in html
        assert "meAvatarFailed" not in html

    def test_header_avatar_vif_src_error(self):
        """Шапка: img по v-if="me && meAvatarUrl" (meAvatarUrl — CDN/blob),
        @error → onMeAvatarError (фолбек CDN → прокси)."""
        html = _Static.read("web/index.html")
        assert 'v-if="me && meAvatarUrl"' in html
        assert ':src="meAvatarUrl"' in html
        assert '@error="onMeAvatarError()"' in html

    def test_chat_avatar_gated_by_photo_file_id(self):
        """Аватар чата: v-if="c.photo_file_id != null && c.avatarUrl" — если
        сервер вернул photo_file_id=null, img не рисуем вовсе (меньше
        404-запросов в прокси); @error → avatarError(c)."""
        html = _Static.read("web/index.html")
        assert 'v-if="c.photo_file_id != null && c.avatarUrl"' in html
        assert ':src="c.avatarUrl"' in html
        assert '@error="avatarError(c)"' in html

    def test_relation_avatar_gated_by_avatar_url(self):
        """Hotfix-R10: аватар участника — v-if="u.avatarUrl" (серверный
        photo_file_id может быть None — вне топ-50; ленивый догруз ставит
        URL, до результата/негатива в листе фолбэк-инициал — avatarInitial);
        @error → avatarError(u). Аватар чата по-прежнему гейтится
        photo_file_id (список чатов без ленивого догруза)."""
        html = _Static.read("web/index.html")
        assert 'v-if="u.avatarUrl"' in html
        assert ':src="u.avatarUrl"' in html
        assert '@error="avatarError(u)"' in html
        assert 'v-if="c.photo_file_id != null && c.avatarUrl"' in html
        assert "avatarInitial(u)" in html

    def test_chat_item_shows_title_and_id(self):
        html = _Static.read("web/index.html")
        assert "c.title || ('Чат ' + c.chat_id)" in html
        # chat_id мелким серым рядом с title
        assert "text-gray-500 font-mono block" in html

    def test_relation_row_shows_username_caption(self):
        html = _Static.read("web/index.html")
        # F-8 (T-872): имя — через resolveRelationName; @username — только
        # если имя не вышло из username (иначе дубль)
        assert "resolveRelationName(u)" in html
        assert "u.username" in html
        # 10.2: пустое имя не рисуем вовсе (id мелким рядом — одно)
        assert 'v-if="resolveRelationName(u)"' in html

    def test_close_and_fullscreen_buttons(self):
        """F-13 (AC-2) + 10.8 (§4): ✕-кнопки закрытия модалок — окно модуля
        (1) + три окна «Доступов» (roles/local/admins); @click closeApp()
        отсутствует; ⛶ (toggleFullscreen) на месте."""
        html = _Static.read("web/index.html")
        assert "@click=\"closeApp()\"" not in html
        assert "@click=\"toggleFullscreen()\"" in html
        assert ">✕</button>" in html
        # 10.8: 4 модальных ✕ (модуль + roles/local/admins «Доступов»).
        assert html.count(">✕</button>") == 4
        assert ">⛶</button>" in html

    def test_sticky_header_class(self):
        html = _Static.read("web/index.html")
        assert ".header-sticky" in html            # CSS-правило
        assert "position: sticky" in html
        assert "z-index: 40" in html               # шапка — без изменений
        assert 'class="main-header header-sticky card-solid' in html
        # Раунд 10.6 (A1/T-1161): sidebar (z-index:45) удалён; скролл — main.
        assert "z-index: 45" not in html
        assert ".app-shell" in html
        assert ".fullscreen-mode .scroll-area" in html
        assert "overscroll-behavior: contain" in html

    def test_gradient_animation_8s(self):
        html = _Static.read("web/index.html")
        # Редизайн 10.5 (T-1098/OD4): старый фиолетовый фон заменён
        # анимированными градиентами эталона на токенах.
        assert "animation: grad-drift 24s" in html
        assert "animation: grad-spin" in html
        assert "gradient 8s" not in html
        assert "gradient 15s" not in html

    def test_relations_enrich_fields_in_app_js(self):
        """Фронт опирается на username/photo_file_id сервера (топ-50);
        у остальных photo_file_id=null — ленивый догруз аватар-прокси
        (loadRelationAvatarsLazy, Hotfix-R10); фолбэк-инициал до результата."""
        src = _Static.read("web/app.js")
        assert "loadRelations: async function" in src
        assert "loadRelationAvatarsLazy" in src
        assert "stageRu(u.stage_auto)" in _Static.read("web/index.html")
