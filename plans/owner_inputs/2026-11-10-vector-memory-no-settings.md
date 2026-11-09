# Owner report (2026-11-10): Vector Memory opens but has no settings

Verbatim root-chat message:

> раздел векторной памяти открылся, но настроек в нем нет, хотя я как админ должен видеть вообще все настройки какие есть в админке

Attached screenshots (2), observed state:
- route `#/modules/embeddings`, breadcrumb «Статус / Модули / Векторная память (Embeddings/GraphRAG)»;
- header: «Векторная память (Embeddings/GraphRAG)», badge GLOBAL, «Работает», button «Управляется из каталога →»;
- single tab «Обзор»; the settings view shows only an empty block:
  «На этой вкладке нет доступных параметров» / «На этой вкладке нет параметров, доступных вашей роли (сервер отфильтровал их по правам)»;
- second screenshot shows the «Поиск по параметрам…» field above the same empty block;
- identity bar shows «Все бот GLOBAL», user «admin».

## Binding interpretation

- The client-side access fix is confirmed working: the section now opens for the owner.
- This is a NEW, separate defect: the module workspace shows no settings for a user who is a global admin with wildcard rights. The owner's expectation, stated explicitly, is that as an admin he sees ALL settings that exist in the admin panel.
- The empty-state text is itself suspect: it asserts the server filtered parameters by rights, which may be false. If the tab simply has no parameters (infrastructure module without its own catalogue tab), saying "filtered by rights" is a false explanation and must be corrected.
- MOD-ACL-UX-01 §5 requires the module workspace to show real current parameters grouped, with no empty intermediary page, and requires an honest empty state.
