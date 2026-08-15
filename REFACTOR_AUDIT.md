# Архитектурный аудит перед рефакторингом

Дата аудита: 10.08.2026  
Область: `app/`, `tests/`, общие шаблоны и статические ресурсы.  
Режим аудита: только чтение. Код приложения, схема и данные БД, API-контракты, CRM и физические панели не изменялись.

## 1. Краткий вывод

В проекте уже есть полезный общий фундамент: `base.html`, `filter-layouts.css`, `scroll.css`, `modal.js`, `dialogs.js`, `global-loader.js`, `smart-search.js`, `combobox.js`, Jinja-фильтры дат и общий сценарий записи `key_write_context.py` + `writer.py`. Главная проблема не в полном отсутствии общих компонентов, а в том, что рядом с ними продолжают существовать page-specific реализации с похожим назначением.

Наиболее безопасно сначала унифицировать визуальные примитивы и форматирование. Поиски, загрузчик и таблицы требуют контрактных UI-тестов. Поиск ключей/панелей, назначения и физическая запись — зоны высокого риска: их нельзя объединять только по внешнему сходству функций.

| Компонент | Реализаций сейчас | Файлы | Что дублируется | Риск | Предлагаемое решение |
|---|---:|---|---|---|---|
| Поиск ключей | 6 | `services/keys.py`, `repositories/key_repository.py`, `services/search.py`, `routers/search.py`, `routers/message.py`, `routers/manual_write.py` | нормализация номера/HEX, выбор типа, ранжирование, статус занятости | HIGH | единый read-only `KeySearchService` с разными профилями запроса |
| Поиск панелей/адресов | 6 | `panel_repository.py`, `services/panels.py`, `services/search.py`, `routers/message.py`, `uk_repository.py`, JS picker'ы | нормализация адреса, поиск по адресу/MAC/входу, LIMIT, формат результата | HIGH | единый `PanelSearchService`, не меняя write API |
| Autocomplete / smart search | 5 основных | `smart-search.js`, `combobox.js`, `message.js`, `manual-write.js`, `uk-detail.js` | debounce, AbortController, Enter/Esc, active item, rendering | MEDIUM | один headless `SmartAutocomplete`, адаптеры источников |
| Loader | 1 глобальный + локальные состояния | `global-loader.js`, `message.js`, `manual-write.js`, `panels.js`, `uk-detail.js` | loading/error/timeout и блокировка кнопок | MEDIUM | сохранить глобальное ядро; стандартизировать локальный async-state |
| Модальные окна | 7 семейств оболочек | `modal.js`, `dialogs.js`, шаблоны keys/employees/panels/UK/message/manual | open/close, focus, dirty form, scroll, размеры | LOW/MEDIUM | общий shell + Jinja macro; специализированное содержимое оставить страницам |
| Карточки сущностей | 8+ семейств | CSS/шаблоны home, keys, employees, panels, UK, message | header/content/actions/status/metadata | LOW | общая геометрия Card, сущностные варианты через modifiers |
| Кнопки | 12 CSS-файлов затрагивают `.btn` | общие CSS + почти все page CSS | размеры, hover/focus, danger/icon/small/disabled | LOW | единая матрица Button в `components.css` |
| Таблицы | 15 шаблонов | `tables.css`, page CSS, registry templates | шапка, scroll, empty, actions, pagination | MEDIUM | Table shell + Pagination macro, без общего data-grid JS |
| Scrollbar | 2 общих файла + page selectors | `scroll.css`, `theme-system.css`, page CSS | scrollbar-color/width/thumb, max-height | LOW | `scroll.css` как единственный источник внешнего вида |
| Даты | 1 общий фильтр + 4 обхода | `templates_config.py`, `dashboard.py`, `settings_crm.html`, `log.html`, JS | парсинг ISO и формат отображения | LOW | обязательный Jinja/JS formatter на границе представления |
| API/fetch | 10+ точек | `panels.js`, `uk*.js`, picker'ы, `global-loader.js`, backend services | JSON parsing, error mapping, timeout, CSRF | MEDIUM/HIGH | тонкий `http-client.js`; доменные API оставить раздельными |
| Занятый ключ | 2 общих потребителя + отдельные UK/employee ветви | `key_write_context.py`, message/manual routers, `uk_keys.py`, employees router | занятость, назначение, уже записанные панели, решение оператора | HIGH | закрепить общий контракт контекста; UK/employee сближать только после тестов |
| Запись на панели | 2 движка верхнего уровня | `writer.py`, `uk_keys.py` | цикл панелей, частичный успех, логирование, CRM result | HIGH | сначала общий DTO результата; сетевую логику не переносить вслепую |

## 2. Поиск

### 2.1 Инвентаризация

| Реализация | Страница / потребитель | Endpoint | Что ищет | Механика UI | Где выполняется | Ограничение / ошибки |
|---|---|---|---|---|---|---|
| `get_search_suggestions()` | Универсальный поиск и поля `data-smart-search` | `GET /api/search/suggestions` | keys, panels/addresses, employees, UK, operations | `smart-search.js`: debounce 180 мс, ↑↓, Enter, Esc, pointer, `onSelect` через события | server, затем клиентское ранжирование | SQL pre-limit 80–1000 по типу, финальный `limit`; fetch timeout и abort |
| `universal_search()` | `/search` | GET/POST `/search` | все основные сущности и журнал | submit формы; подсказка может auto-submit | server | отдельная строгая ветвь address+apartment; крупные pre-limit до 5000 |
| `search_keys_for_selection()` | picker ключа, UK | `GET /api/keys/search`, делегат из UK repo | свободные/доступные keys с типом | общий smart autocomplete в UK detail | server | ранжирование exact/prefix, `LIMIT`; исключение уже выданных УК |
| `_keys_filter_sql()` + `get_keys_page()` | База ключей | `GET /keys` | ключ и активное назначение: адрес, квартира, владелец | серверная форма + smart suggestions | server, JOIN/EXISTS | пагинация LIMIT/OFFSET; строгий apartment token |
| `find_keys()` / `find_key()` | message/manual/employee routes | HTML POST routes | точный номер или HEX, опционально тип | после submit | server | возвращает ambiguity вместо fuzzy подмены |
| `_build_key_rows()` | «Из сообщения» | `POST /message/preview` | распознанные ключи по группам | форма → preview | parser + DB lookup | сохраняет тип из текста и leading zero; ошибки выводятся строками |
| `get_panel_page()` | Реестр панелей | `GET /panels` | address/name/MAC/IP/id + filters | server form, query в URL | server | LIMIT/OFFSET, нормализованный поиск |
| `message_panel_search()` | ручные дополнительные панели в message/manual | `GET /message/panels/search` | вся активная база панелей | message debounce 260 мс; manual 280 мс; Enter; button | server, общий endpoint | limit задаёт route; AbortController, manual timeout 10 с, локальная ошибка |
| `search_group_panels()` | выдача ключа УК | `GET /uk/{id}/available-panels` | только панели выбранной УК | input debounce 220 мс + Enter/button | server | `limit=60`, нормализация; отдельный renderer |
| `get_employee_page()` | Сотрудники | `GET /employees` | ФИО, телефон, должность, отдел, ключи | server form; дополнительно local smart filter в модалях | server | LIMIT/OFFSET, `SMART_NORM`, EXISTS по ключам |
| `get_group_page()` | Реестр УК | `GET /uk` | название, контакты, адрес, CRM login | server form | server | LIMIT/OFFSET |
| `get_operations()` | Журнал | `GET /log` | user/action/object/details + structured filters | server form | server | LIMIT/OFFSET; параметризованные условия |
| `users-filter.js` | Пользователи | `/users` | роль/статус среди уже загруженных карточек | click/filter, URL state | local | не масштабируется как server registry |
| `employees.js` local filters | modal/list fragments | нет | уже загруженные варианты | input event | local | использует общий normalize, но отдельную фильтрацию |

### 2.2 Что действительно можно объединить

1. **Нормализацию**: `app/search_utils.py` уже правильный центр. Убрать локальные копии следует только после тестов пунктуации, `ё/е`, квартир, ведущих нулей и MAC.
2. **Picker ключа**: API `/api/keys/search` должен стать единым источником для UK, employee и других форм выбора существующего ключа. Профиль обязан явно задавать `available_only`, тип, исключение текущего владельца и limit.
3. **Picker панели**: `/message/panels/search` фактически уже общий для message/manual, но название endpoint привязано к странице. Возможный будущий контракт: `/api/panels/search` с `scope=all|uk`, `group_id`, `limit` и одинаковым DTO.
4. **Нельзя объединять** универсальный поиск и picker простым вызовом одной SQL-функции: универсальный поиск допускает fuzzy/ranking по разным сущностям, picker обязан быть предсказуемым и не подменять технический идентификатор.

### 2.3 Риски

- В `services/search.py` разные предельные выборки (`80`, `100`, `500`, `800`, `1000`, `1500`, `5000`) оправданы разной сущностью, но не документированы как профили.
- Адрес+квартира имеет строгую специальную ветвь; перенос в «общий fuzzy search» вернёт ложные совпадения квартир с panel id/IP/key number.
- Message и manual используют один endpoint панелей, но два почти одинаковых JS renderer'а. Это хороший кандидат на UI-объединение без изменения backend.
- Users filtering выполняется в браузере и не должно автоматически стать образцом для реестров с десятками тысяч записей.

## 3. Loader и асинхронные операции

### 3.1 Что уже реализовано

`app/static/js/global-loader.js` содержит:

- token-based `show()` / `hide(requestId)` через `Map` активных запросов;
- верхнюю полосу сразу и overlay через 260 мс;
- перехват `fetch`, XHR, HTML forms и внутренних переходов;
- `finally` в `runWithLoader()`;
- safety timeout 120 с по умолчанию;
- HTML form async timeout 45 с;
- исключения для download/export и `data-no-loader`;
- reset на `pageshow`.

Это следует сохранять как один глобальный компонент, а не переписывать.

### 3.2 Локальные состояния

- `manual-write.js`: панельный поиск с AbortController, timeout 10 с и локальным сообщением.
- `message.js`: аналогичный поиск с AbortController, но собственный текст состояния и renderer.
- `panels.js`: polling мониторинга 1.4/10 с, check/reboot/snapshot с отдельной блокировкой кнопок.
- `uk-detail.js`: события `smart-autocomplete:loading/loaded/error` для ключей и отдельный debounce для панелей.
- `smart-search.js`: timeout/abort внутри `fetchJson()` и отмена предыдущего запроса.

### 3.3 Потенциальные зависания

| Место | Причина риска | Текущая защита | Рекомендация |
|---|---|---|---|
| navigation loader | другой capture-handler может отменить/перехватить переход после проверки `defaultPrevented` | safety 30 с | сохранить safety; дать SPA-like обработчикам явный `data-no-loader` |
| native `form.submit()` | страница может не уйти из-за ошибки другого кода | общий safety 120 с | не использовать без явного async wrapper для операций записи |
| XHR без собственного timeout | `loadend` не наступит при вечном TCP ожидании | safety token 120 с | общий http client должен задавать timeout, не только loader guard |
| custom button loading | исключение до ручного снятия disabled/class | зависит от страницы | общий `withButtonPending(button, task)` с `finally` |
| HTML response replacement | JSON успешен, но `document.write`/validation падает | loader закрыт в `finally` до render | показывать app dialog; не оставлять старую форму disabled |
| polling panels | overlapping/background state при медленном ответе | следующий timer ставится после await | сохранить serial polling, явно `globalLoader:false` |

Временные `console.debug/info` записи загрузчика и сценариев записи удалены при production cleanup. Ошибки по-прежнему проходят через прикладные диалоги и `console.error`, а серверные ошибки — через стандартный журнал приложения без вывода секретов.

## 4. Модальные окна

### 4.1 Общая оболочка

`modal.js` уже объединяет `.app-modal`, `.uk-modal`, `.uk-detail-modal`, `.keys-modal`, `.employee-modal`, `.panels-modal`, `.modal-backdrop`. Есть:

- запоминание и возврат фокуса;
- body lock;
- focus trap;
- dirty-form snapshot и подтверждение;
- запрет закрытия кликом по backdrop;
- явное закрытие через X;
- Esc намеренно перехватывается и **не закрывает** окно.

`dialogs.js` отдельно реализует alert/confirm/danger-confirm с Enter/Esc и фокусом. Это оправданно: диалог подтверждения и форма-модалка имеют разные правила.

### 4.2 Семейства разметки

1. Keys: пять `.modal-backdrop` в `keys.html`.
2. Panels: add/edit/import `.panels-modal`.
3. Employees: add/edit/create-key `.employee-modal-card`.
4. UK list/detail: `.uk-modal-card`, несколько форм.
5. Message panel picker: `.message-panel-picker__dialog`.
6. Manual panel picker: `.manual-panel-picker__dialog`.
7. Global confirmation: один блок в `base.html`.

### 4.3 Кандидат на рефакторинг

Создать Jinja macro/partial только для shell: backdrop, header, close button, scroll surface, footer. Не переносить внутрь универсального компонента формы и page-specific state. CSS-размеры оформить modifiers `--sm`, `--md`, `--wide`; адаптивность и scrollbar оставить общими.

Обнаруженный дефект качества: строки подтверждения dirty-form в `modal.js` отображаются в исходнике как mojibake. До рефакторинга нужно отдельным тестом установить, это проблема файла/кодировки чтения или реальный текст в браузере.

## 5. Smart Search, autocomplete и combobox

### 5.1 `smart-search.js`

Наиболее полный общий компонент: debounce 180 мс, AbortController, timeout, menu positioning, ↑↓, Enter, Esc, pointerdown, active option, focus/blur, события выбора/загрузки/ошибки и optional submit-after-select.

### 5.2 `combobox.js`

Прогрессивно улучшает обычный `<select>`: локальный поиск по options, keyboard navigation, Enter/Esc, popup positioning, native invalid integration. Это другой use case; объединять его с remote autocomplete в один класс не обязательно.

### 5.3 Дубли

- panel picker в `message.js` и `manual-write.js`: почти одинаковые debounce/search/render/add/remove/count.
- UK panel picker: собственные debounce 220 мс, Enter и renderer.
- employees modal search и users filters: локальная фильтрация без общего lifecycle.

Предложение: оставить `combobox.js`; развить `smart-search.js` в headless API с source adapter и renderer callback; вынести panel picker в один `panel-picker.js`. Не создавать ещё один `smart-autocomplete.js`, пока не определён контракт миграции существующего `smart-search.js`.

## 6. Карточки и detail sidebar

Повторяются структуры:

- dashboard action/stat cards (`index.html`);
- keys stat cards, selected-key sidebar, assignment/history cards;
- employee list/profile/key cards и inspector;
- panel rows + inspector;
- UK rows, linked panel cards, inspector;
- message/manual panel cards;
- settings menu cards;
- universal search result cards.

Уже есть `detail-sidebar.css`, `.panel`, `.badge`, общие цветовые tokens. Безопасный общий слой: `.entity-card`, `__header`, `__meta`, `__actions`, `--selected`, `--compact`. Доменные карточки не следует превращать в один огромный macro с десятками параметров.

## 7. Кнопки

Строка `.btn` встречается в 12 CSS-файлах. Часть — нормальные theme/page context overrides, но размеры и состояния размазаны по `components.css`, `filter-layouts.css`, `theme-system.css` и page CSS.

Целевая матрица:

- `.btn` — базовая высота, padding, font, radius, focus-visible;
- `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-success`;
- `.btn-icon`, `.btn-sm`;
- единый `[disabled]`/`aria-disabled`;
- page CSS меняет только layout (width/grid), не геометрию кнопки.

До удаления правил требуется visual regression для dark/light и 1920/1366/900 px.

## 8. Таблицы и пагинация

Таблицы присутствуют минимум в 15 шаблонах. Общими являются sticky/header tone, row borders, selected row, action cells, empty row, internal scroll и pagination. Однако columns и row actions доменные.

Кандидаты:

- Jinja macro pagination с сохранением query params;
- macro empty row;
- `.registry-table`, `.registry-scroll`, `.registry-row--selected`, `.registry-actions`;
- общий размер текста и focus-visible для clickable rows.

Не рекомендуется сейчас внедрять общий JS data-grid: keys/panels/employees/UK/log имеют разные серверные фильтры и разные sidebars.

## 9. Scrollbar

`scroll.css` уже содержит общий scrollbar foundation, но `theme-system.css` повторно перечисляет много page selectors, а `uk.css`, `keys_log.css`, `employees.css` задают собственные overflow/max-height.

Разделить ответственность:

- `scroll.css`: только внешний вид scrollbar и utility `.custom-scroll`/`.modal-scroll`;
- component/page CSS: только `overflow`, `max-height`, layout;
- не копировать `::-webkit-scrollbar*` в page CSS.

## 10. Даты

Общий источник уже есть: `templates_config.py::format_datetime()` и `format_datetime_seconds()`, зарегистрированные как globals и filters. Большинство новых шаблонов используют `|datetime`.

Обходы общего слоя:

- `log.html` выводит `created_date or created_at` для разделённой даты/времени;
- `settings_crm.html` вызывает `strftime` прямо в шаблоне;
- `dashboard.py::format_monitor_sync()` имеет специальное относительное/календарное представление;
- динамические значения panels форматируются также в JS и должны совпадать с сервером.

Решение LOW risk: один server formatter + один JS `formatDateTime`, одни тестовые примеры timezone/seconds/null. Специальный dashboard label оставить отдельным.

## 11. API и service layer

### 11.1 Frontend

`fetch` вызывается напрямую в panel monitoring/actions, UK credential reveal, UK picker, message/manual picker и smart search. Повторяются:

- проверка `response.ok`;
- `response.json()`;
- AbortController/timeout;
- локальный loading/error;
- CSRF headers для mutating calls;
- блокировка кнопки.

Будущий `http-client.js` может дать `getJson`, `postJson`, timeout, abort normalization и safe error. Он не должен автоматически включать overlay: loader mode обязан задавать вызывающий компонент.

### 11.2 Backend

- `panel_api.py`: физические панели, auth/timeout/status mapping.
- `crm.py`: внешняя CRM, session/auth/sanitization.
- repositories: PostgreSQL access.
- routers: HTTP parsing/response.

Эти границы в целом правильные. Нельзя создавать «универсальный API service», смешивающий CRM и панели. Общими могут быть только result DTO, timeout/error taxonomy и audit metadata.

## 12. Бизнес-логика ключей

### 12.1 Общая ветвь message/manual

Уже переиспользуются:

- `get_key_write_context()` — активное назначение и известные панели;
- `enrich_key_write_rows()` — состояние относительно выбранных панелей;
- `resolve_key_write_decision()` — `reassign` / `add_panels`, preserve/replace, action required;
- `write_key_to_panels()` — обработка набора панелей и частичного результата.

Это сильная база. Ее нельзя заменять page-specific функциями.

### 12.2 Отдельные ветви

- UK: `uk_keys.py::_run_programming()` и `issue_key()`; учёт `uk_key_issues`/`uk_key_programmings`, CRM credentials группы, retry/unlink/remove.
- Employee: router + `employee_repository.py` назначают ключ сотруднику; физическая запись вызывает общий `write_key_to_panels()` только в соответствующем сценарии.
- Assignment editor: `key_repository.py::update_key_assignment()` меняет только CRM-назначение и хранит историю.

### 12.3 Что нельзя менять без отдельного проекта

- момент, когда создаётся/закрывается assignment;
- семантику «переназначить» против «только добавить панели»;
- idempotency физической панели;
- статус ключа после частичного успеха;
- UK issue/programming primary link;
- порядок CRM и panel side effects;
- audit log payload и retry semantics.

HIGH-risk рефакторинг допустим только через characterization tests: free, occupied, partial, already-all, timeout, auth error, one panel failed, duplicate submission, DRY_RUN.

## 13. CSS-дубли

Крупнейшие файлы: `pages/uk.css` (~5537 строк), `pages/keys_log.css` (~3062), `pages/employees.css` (~2656), `pages/message.css` (~1317), `light-theme.css` (~1000), `theme-system.css` (~852).

Признаки дублирования:

- `.btn` затрагивают 12 файлов;
- `.panel` — 11;
- modal backdrop/card — 4;
- app combobox — 4;
- filter-bar — 3;
- scrollbar foundation — `scroll.css` и `theme-system.css` плюс страницы;
- page CSS повторяют dark/light значения вместо опоры только на tokens.

Не каждое повторение селектора является ошибкой: `light-theme.css` и responsive overrides ожидаемы. Перед удалением нужно построить cascade map по load order из `base.html`, затем переносить один компонент за раз.

## 14. JS-дубли

Наиболее явные:

1. Message/manual additional-panel picker: поиск, AbortController, debounce, render, selected count, duplicate check, add/remove.
2. Open modal helpers в `panels.js` и `employees.js` рядом с общим `AppModal`.
3. Clickable row keyboard handling в `uk.js`, `panels.js`, `employees.js`.
4. Button pending + fetch/json/error в panels/UK.
5. Local normalize/filter logic поверх общего `search_utils`/`smart-search`.

Кандидаты: `panel-picker.js`, `clickable-row.js` (или data-attribute в base), `async-action.js`. Вначале следует переключить один потребитель и сравнить поведение, а не массово удалять обработчики.

## 15. HTML/Jinja-дубли

Кандидаты на partial/macro:

- modal shell/header/footer;
- registry pagination;
- empty state;
- status badge;
- filter field/search wrapper;
- panel card (auto/manual modifiers);
- inspector row `dt/dd`;
- operation history row.

Не стоит превращать целые страницы в один универсальный registry macro: это скроет различия прав, фильтров, columns и действий.

## 16. Риски по уровням

### LOW

- единая геометрия buttons;
- scrollbar appearance;
- обязательное форматирование дат через существующие filters;
- базовый card shell;
- modal shell/macro без изменения close semantics.

### MEDIUM

- SmartSearch/autocomplete lifecycle;
- combobox integration;
- table/pagination/empty-state;
- global/local loader coordination;
- общий frontend HTTP client;
- перенос page modal openers на `AppModal`.

### HIGH

- backend key search и ambiguity rules;
- panel/address search и exact apartment handling;
- active key assignments;
- occupied key decisions;
- physical panel writes and retries;
- UK issue/programming model;
- CRM requests/authentication/order of side effects.

## 17. Предлагаемая последовательность рефакторинга

1. **Зафиксировать поведение**: добавить characterization tests и визуальные baseline-снимки; не менять production data.
2. **LOW: даты**: убрать прямые выводы/`strftime`, добавить общий JS formatter.
3. **LOW: scrollbar/buttons/tokens**: переносить по одному компоненту, проверять обе темы и ширины.
4. **LOW: modal shell/cards**: Jinja macros без изменения JS behavior и explicit-close.
5. **MEDIUM: pagination/table shell**: сначала UK/employees как похожая пара, затем panels/keys/log.
6. **MEDIUM: panel picker JS**: объединить message/manual на существующем endpoint; сохранить локальный loader.
7. **MEDIUM: smart autocomplete**: адаптировать UK и local pickers к `smart-search.js`, не смешивая remote и native select.
8. **MEDIUM: http-client/button pending**: только после тестов abort/timeout/error/CSRF/global-loader.
9. **HIGH: единые search profiles**: DTO и contract tests, затем новый `/api/panels/search`; старые endpoints временно делегируют.
10. **HIGH: key write result DTO**: унифицировать только представление результата writer/UK, не side effects.
11. **HIGH: assignments/UK/employee**: отдельный ADR и миграционный план; рефакторить после полного набора idempotency и partial-success тестов.
12. Удалять старый код только после переключения всех потребителей и подтверждения тестами/визуальной проверкой.

## 18. Практический первый этап

Рекомендуемый первый PR без бизнес-риска:

1. Тесты `format_datetime` + устранение двух прямых обходов.
2. Выделение modal Jinja shell без изменения `modal.js`.
3. Консолидация scrollbar appearance в `scroll.css`.
4. Документированная button matrix; миграция одной страницы.
5. Никаких изменений repositories, assignments, CRM и panel API.

После этого второй PR: общий panel picker для message/manual с текущим `/message/panels/search`, тестами keyboard/mouse/duplicate/timeout и визуальной проверкой.

## 19. Что намеренно не сделано

- файлы приложения не редактировались;
- таблицы, миграции и данные PostgreSQL не затрагивались;
- тестовые и рабочие БД не открывались для записи;
- реальные CRM/API panel requests не выполнялись;
- устаревший или временный код не удалялся;
- существующие незавершённые изменения рабочего дерева не исправлялись и не форматировались.
