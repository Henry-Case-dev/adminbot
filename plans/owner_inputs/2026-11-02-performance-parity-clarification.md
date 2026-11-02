# OI-2026-11-02-PERF-PARITY — уточнение владельца по треку P (verbatim)

**Вид:** amendment (уточнение границ уже поставленного трека P)
**Получено:** 2026-11-02
**Целевые задачи:** трек P (`plans/current_task.md` §P, P-01…P-16)
**Статус сверки:** reconciled в `docs/track-p-performance-parity.md`
**Способ сохранения:** дословный текст передан архитектурному субагенту как binding amendment; исходный канал — родительская сессия (id сообщения недоступен локально).

## Дословный текст

> optimisation may touch ONLY code, loading, rendering, requests, caching and internal architecture.
> Forbidden: changing, simplifying, hiding, disabling, trimming or visually degrading any existing
> functionality, UI, animations, glass/refraction effects, background, layout or interaction behaviour.
> No lightweight modes, no silent fallbacks, no speed from UX degradation. Only internal optimisation
> with FULL visual and functional parity. ANY deviation = regression = release blocker, even if
> metrics improve.

## Что это меняет в текущем контракте трека P

1. Ранжирование кандидатов P — только по внутренним выигрышам; любые «ускорения» за счёт сокращения
   видимого поведения выведены из списка кандидатов, а не отложены «на потом».
2. Паритет (визуальный и функциональный) становится отдельным блокирующим гейтом пакета, а не одной
   строкой P-12.
3. Приёмочные числа производительности не могут перевесить зафиксированное расхождение паритета:
   расхождение аннулирует пакет независимо от метрик.
4. Дефолты эффектов (`UI_LIQUID_GLASS_LIB`, `UI_GLASS_TIER_OVERRIDE`, `UI_LENS_MAX_NODES`,
   `UI_POLYGON_BG_ENABLED`, `UI_AURORA_FLOW_V2`, `UI_AURORA_BG_ENABLED`) заморожены: их изменение —
   не оптимизация, а изменение UX.
