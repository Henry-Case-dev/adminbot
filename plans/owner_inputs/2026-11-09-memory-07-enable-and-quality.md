# Owner correction (2026-11-09): MEMORY-07 must ship enabled; project rule for first-deploy activation

Verbatim owner instruction (root chat, 2026-11-09):

> В релизе 2.58.168 MEMORY-07 снова поставлена с выключенным по умолчанию `MCA_MEMORY_COMMUNITIES_ENABLED`. Исправить.
>
> Это пет-проект. Зафиксировать на уровне проекта обязательное правило: все новые функции при первом production-деплое глобально включены по умолчанию. Тестовые, теневые и отложенные активации не должны становиться постоянным состоянием готовой функции. Существующие пользовательские настройки не сбрасывать.
>
> Для MEMORY-07 включить флаг, запустить реальную сборку сообществ и проверить использование в тематическом retrieval. Одновременно устранить деградацию качества: при 99,87% legacy-связей не выдавать бессмысленные сообщества за доказанные, не засорять поиск и визуальный граф нейтральными "Сообщество N". Слабые сообщества должны корректно фильтроваться или понижаться в ранжировании, а проблема provenance должна решаться в своём источнике.
>
> Не оставлять флаг выключенным как способ закрыть проблему. Выполнить исправление, тесты, деплой и реальные проверки. Технические блокеры возвращать на исправление, не на human gate. Отчитаться по effective-state, сформированным данным, влиянию на поиск и результатам проверки.

Binding consequences:
- Project-wide rule (all new features): at the first production deploy of a ready feature it is globally enabled by default. Shadow/test/deferred activation must not become the permanent state of a finished feature. Existing user/chat overrides are preserved, never reset.
- MEMORY-07: enable the flag, run a real community build in production, verify thematic retrieval actually consumes the active build.
- Quality: weak communities must be filtered or demoted, never presented as proven; neutral "Сообщество N" must not pollute search or the visual graph; the provenance problem is fixed at its source, not masked downstream.
- Disabling the flag is not an acceptable way to close the problem.
