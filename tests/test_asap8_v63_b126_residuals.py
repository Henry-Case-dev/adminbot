"""B12.6 (v6.3, ledger 16.10) — три остатка, закрытые негативными тестами.

Источники остатков: `evidence/v63-close/preserve-and-workflow-audit.md` §4,
`v63-agent-close-2026-10-16.md` §5, `prep-rfl-binding.md` §B12.6.

Закрываемые клаузы (исходник L00414):
  1. «ошибочный адресат» — цитата/высказывание НИКОГДА не биндится к
     неверному адресату: собственное сообщение-триггер исключается из
     кандидатов исторической ступени резолвера (M-2 wiring), sender не
     назначается автором по умолчанию, ≥2 авторов → ambiguous
     (`unknown` > hallucinated binding; services/quote_resolver.py).
  2. «GraphRAG hallucinated stats» — число в стат-контексте обязано
     сходиться с NumericClaim РЕАЛЬНОГО измерения: measure() по настоящей
     БД → MetricResult/claims → numeric-гард бракует выдуманное число
     (коррекция verified_phrase / оговорка; services/chat_statistics.py +
     services/negative_constraints.py, ADR-1028-12 D5).
  3. «side effects измеримы» — сквозной перенос памяти даёт полный
     измеримый след: per-table moved counts, backup-журнал покрывает
     КАЖДУЮ переадресованную строку, суммарные счётчики строк не меняются
     (0 DELETE), integrity-отчёт ок, повтор идемпотентен
     (services/chat_migration.py).

TEST-LIFECYCLE: REGRESSION owner=B12.6
R17: только синтетические данные, никаких реальных переписок.
"""
import time

import pytest

from services.database import DatabaseService
from services import chat_statistics as cs
from services import negative_constraints as nc
from services import quote_resolver as qr

CHAT = -100500
NOW = 1_700_000_000


async def _open():
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


# ══ 1. Негатив «ошибочный адресат» (mca-22 quote resolver, ступень 6) ════════

class TestWrongAddresseeNeverBound:
    @pytest.mark.asyncio
    async def test_trigger_exclusion_and_sender_never_author(self):
        """Ручная `>`-цитата, совпадающая ТОЛЬКО с собственным
        сообщением-триггером sender'а: без исключения триггера резолв НЕ
        назначает sender'а автором (ambiguous); с исключением триггера
        (боевой wiring) — честный unresolved. Неверный адресат не биндится."""
        db = await _open()
        try:
            trigger_tg_id = 700
            await db.save_smart_message(
                1, CHAT, "я говорил что биллинг переезжает на SBP давно",
                None, NOW, "text", "Отправитель",
                message_id=trigger_tg_id)
            res = await qr.resolve_quote(
                db, chat_id=CHAT, sender_entity_id=1,
                quote_text="что биллинг переезжает на SBP давно",
                bot_user_id=42)
            # sender НИКОГДА не автор по умолчанию: совпадение с собственной
            # репликой — не proof авторства
            assert res.status == qr.QUOTE_AMBIGUOUS
            assert res.quote_speaker_entity_id != 1
            # боевой wiring: триггер исключён из кандидатов → unresolved
            res2 = await qr.resolve_quote(
                db, chat_id=CHAT, sender_entity_id=1,
                quote_text="что биллинг переезжает на SBP давно",
                bot_user_id=42, exclude_tg_message_id=trigger_tg_id)
            assert res2.status == qr.QUOTE_UNRESOLVED
            assert res2.quote_speaker_entity_id is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_two_authors_ambiguous_and_single_author_resolved(self):
        """Текст цитируют двое разных участников → ambiguous (не биндится ни
        к одному — негатив «ошибочного адресата»); контроль: единственный
        уверенный чужой автор резолвится в НЕГО, не в sender'а."""
        db = await _open()
        try:
            text = "итоговое решение по биллингу принял совет директоров"
            await db.save_smart_message(
                10, CHAT, text, None, NOW - 60, "text", "Анна")
            await db.save_smart_message(
                20, CHAT, text, None, NOW - 30, "text", "Борис")
            res = await qr.resolve_quote(
                db, chat_id=CHAT, sender_entity_id=1, quote_text=text,
                bot_user_id=42)
            assert res.status == qr.QUOTE_AMBIGUOUS
            assert res.quote_speaker_entity_id is None
            # контроль (негатив не вакуумный): один автор → resolved к нему
            db2 = await _open()
            try:
                await db2.save_smart_message(
                    10, CHAT, text, None, NOW - 60, "text", "Анна")
                res2 = await qr.resolve_quote(
                    db2, chat_id=CHAT, sender_entity_id=1, quote_text=text,
                    bot_user_id=42)
                assert res2.status == qr.QUOTE_RESOLVED
                assert res2.quote_speaker_entity_id == 10
            finally:
                await db2.close()
        finally:
            await db.close()


# ══ 2. Негатив «GraphRAG hallucinated stats» (mca-15 D5 + mca-08 G2) ═════════

class TestGraphRagHallucinatedStats:
    @pytest.mark.asyncio
    async def test_hallucinated_count_never_survives_guard(self):
        """Контур GraphRAG-измерения end-to-end на реальной БД: measure()
        (настоящий SQL/FTS) → MetricResult → NumericClaim → numeric-гард.
        Выдуманное число в стат-контексте НЕ публикуется: коррекция до
        verified_phrase измерения; проверенный черновик проходит
        байт-в-байт."""
        db = await _open()
        try:
            rows = [
                (1, 10, "шиз обсуждаем", 1000, "Вася"),
                (2, 20, "шиз пришёл", 2000, "Вася"),
                (3, 10, "опять шиз", 3000, "Вася"),
                (4, 30, "без темы", 4000, "Петя"),
                (5, 10, "шизофрения не в счёт? шиз в счёт", 5000, "Вася"),
            ]
            for (rid, uid, text, ts, name) in rows:
                await db.db.execute(
                    "INSERT INTO smart_messages(id,user_id,chat_id,text,"
                    "timestamp,author_name) VALUES(?,?,?,?,?,?)",
                    (rid, uid, CHAT, text, ts, name))
            await db.db.executemany(
                "INSERT INTO smart_messages_fts(rowid,text) VALUES(?,?)",
                [(r[0], r[2]) for r in rows])
            await db.db.commit()

            query = cs.StatsQuery(chat_id=CHAT, match_mode=cs.MATCH_PREFIX,
                                  terms=("шиз",))
            measured = await cs.measure(db, query)
            assert measured["status"] == "ok" and measured["value"]
            real_value = int(measured["value"])
            mr = cs.build_metric_result(measured, query)
            claims = cs.claims_for_result(mr)
            assert claims and int(claims[0].value) == real_value
            contract = nc.NumericContract(
                claims=tuple(claims), verified_phrase=mr.verified_phrase,
                stats_expected=True)

            # галлюцинированная статистика (числа ≠ измерению)
            bad_a, bad_b = real_value + 37, real_value + 58
            hallucinated = (f"ну держи: было {bad_a} упоминаний "
                            f"в {bad_b} сообщениях, сам считал")
            text, stats = nc.apply_numeric_guard(hallucinated, contract)
            assert stats.get("mismatch") is True
            # ни одно галлюцинированное число не выжило в стат-контексте
            surviving = {canon for canon, _pos, _units
                         in nc._stat_context_numbers(text)}
            assert str(bad_a) not in surviving
            assert str(bad_b) not in surviving
            assert str(real_value) in text          # проверенное число
            assert stats["reason"] in (nc.NUMERIC_CLAIM_CORRECTED,
                                       nc.NUMERIC_CLAIM_FALLBACK)

            # тот же гард не трогает честный ответ (байт-паритет)
            honest = f"нашёл {real_value} сообщений по «шиз»"
            text2, stats2 = nc.apply_numeric_guard(honest, contract)
            assert text2 == honest and stats2 == {}
        finally:
            await db.close()


# ══ 3. «Side effects измеримы» (B09/B12.6: полный измеримый след) ═══════════

class TestMigrationSideEffectsMeasurable:
    @pytest.mark.asyncio
    async def test_move_leaves_complete_measurable_trail(self):
        """Перенос памяти old→new измерим по каждому носителю: moved-counts
        в результате, backup-журнал покрывает каждую переадресованную
        строку 1:1, суммарные счётчики строк не меняются (0 DELETE),
        integrity-отчёт ok, повторный прогон — 0 строк (идемпотентность)."""
        OLD, NEW = CHAT, -100999
        db = await _open()
        try:
            n_msgs, n_facts = 7, 4
            for i in range(n_msgs):
                await db.save_smart_message(
                    77, OLD, f"реплика {i}", None, NOW + i, "text", "A")
            fids = []
            for i in range(n_facts):
                fids.append(await db.insert_graph_fact(
                    OLD, f"факт {i}", "chat_history", None))
            await db.upsert_running_summary(
                OLD, "конспект", NOW - 600, NOW, 5, float(NOW), float(NOW))
            await db.db.commit()

            carriers = ("smart_messages", "graph_facts",
                        "chat_running_summary")

            async def _counts():
                out = {}
                for t in carriers:
                    cur = await db.db.execute(
                        f"SELECT COUNT(*) AS n FROM {t}")
                    out[t] = (await cur.fetchone())["n"]
                return out

            before = await _counts()
            started = time.perf_counter()
            from services.chat_migration import (migrate_chat_memory,
                                                 verify_chat_memory_integrity)
            result = await migrate_chat_memory(db, OLD, NEW)
            elapsed_s = round(time.perf_counter() - started, 3)

            # 1) каждое перемещение посчитано и репортится по таблицам
            assert result["errors"] == [], result["errors"]
            assert result["moved"]["smart_messages"] == n_msgs
            assert result["moved"]["graph_facts"] == n_facts
            assert result["moved"]["chat_running_summary"] == 1

            # 2) backup-журнал покрывает каждую переадресованную строку 1:1
            #    (для стандартных таблиц, rowid ≠ chat_id-алиас)
            for table, moved_n in result["moved"].items():
                if table == "chat_running_summary":
                    continue      # известный gap — отдельный xfail-тест ниже
                cur = await db.db.execute(
                    "SELECT COUNT(*) AS n FROM chat_migration_backup "
                    "WHERE table_name = ?", (table,))
                assert (await cur.fetchone())["n"] == moved_n

            # 3) 0 DELETE: суммарные счётчики строк не изменились
            after = await _counts()
            assert before == after

            # 4) под old пусто, целостность подтверждена; замер времени
            report = await verify_chat_memory_integrity(db, OLD, NEW)
            assert report["ok"] is True, report["residual_old_rows"]
            assert elapsed_s > 0

            # 5) идемпотентность: повтор — ровно 0 строк side effects
            second = await migrate_chat_memory(db, OLD, NEW)
            assert second["moved"] == {} and second["backup_rows"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="ЗАМЕР B12.6 21.10.2026: chat_running_summary имеет "
               "PK=chat_id=алиас rowid; у суперчатов chat_id отрицательный, "
               "поэтому backup-петля (WHERE chat_id=? AND rowid > -1) читает "
               "0 строк, но UPDATE переносит строку — конспект попадает в "
               "перенос БЕЗ backup-журнала. Нарушает контракт «backup ДО "
               "записи» (services/chat_migration.py, REV-W1 F1). Фикс — "
               "отдельный лейн в services/; после фикса маркер снять.")
    async def test_backup_covers_running_summary_negative_pk(self):
        """Дефект из замера B12.6: строка бегущего конспекта переносится
        без backup-записи (PK-алиас rowid + отрицательный chat_id).
        strict-xfail: сегодня падает (дефект воспроизведён); после починки
        services/ станет XPASS и потребует снятия маркера."""
        OLD, NEW = -100700, -100800
        db = await _open()
        try:
            await db.upsert_running_summary(
                OLD, "конспект", NOW - 600, NOW, 5, float(NOW), float(NOW))
            await db.db.commit()
            from services.chat_migration import migrate_chat_memory
            result = await migrate_chat_memory(db, OLD, NEW)
            assert result["errors"] == []
            assert result["moved"].get("chat_running_summary") == 1
            cur = await db.db.execute(
                "SELECT COUNT(*) AS n FROM chat_migration_backup "
                "WHERE table_name = 'chat_running_summary'")
            assert (await cur.fetchone())["n"] == 1   # сегодня: 0 → xfail
        finally:
            await db.close()
