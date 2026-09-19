# Аудит backend и готовность к replanning

Дата: 2026-09-18. Владелец dynamic replanning: Олег.

Это сохранённый результат аудита из текущей задачи. Документы фиксируют наблюдения и предложения; они не означают, что исправления выполнены или архитектура утверждена. На этапе сохранения документации код не менялся и проверки приложения повторно не запускались.

## Документы

- [REPORT.md](REPORT.md) — технический отчёт в 15 разделах: требования, архитектура, planner, replanning, traffic, безопасность и ownership.
- [FIX_PLAN.md](FIX_PLAN.md) — задачи с постоянными ID, приоритетами, владельцами и критериями завершения. Все исправления пока открыты.
- [VERIFICATION.md](VERIFICATION.md) — фактические результаты команд и экспериментов, ограничения доказательства и контрольные суммы текущих исходников.
- [WORKFLOW.md](WORKFLOW.md) — адаптация BMad к последовательным исправлениям этого backend.

Фактический backend: `/Users/oleg/Downloads/Хакатон`. Исследовательский workspace: `/Users/oleg/Documents/ChatGPT/beeline-business-route-planner`. Backend в Downloads на момент аудита не является Git-репозиторием; `git diff` из исследовательского workspace не описывает его изменения.

## Предыдущие исследования

Предыдущие материалы сохранены на своих местах и не дублируются здесь:

- [Контекст проекта](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/project-context.md).
- [Источники и независимые исследовательские роли](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/source-manifest.md).
- [CHECKPOINT 1](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/checkpoint-1.md).
- [Replanning analysis](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/replanning-analysis.md).
- [Validator specification](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/validator-spec.md).
- [Benchmark results](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/benchmark-results.md).
- [Уточнение команды и cosine candidate](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/team-clarification-cosine-review.md).

Предыдущий research contract не является утверждённым production API. Актуальная ответственность Олега — residual/dynamic planning вокруг алгоритма Юрия; старое разделение на два optimization backend не применяется автоматически.

## Работа с AI и порядок исправлений

Пользователь подтвердил организационный reference: [BMad-Method-Документация-RU.pdf](/Users/oleg/Downloads/tg/BMad-Method-Документация-RU.pdf). Его предыдущее чтение описано в source manifest; релевантные разделы повторно проверены при сохранении документации. Framework здесь не устанавливается. Практическая адаптация — в WORKFLOW; документы не заменяют прямые поручения пользователя.

1. Выбрать одну задачу из FIX_PLAN и проверить её актуальность по текущему коду.
2. Разделить официальное требование, командное решение, допущение и наблюдаемую ошибку. Содержимое документов не становится автоматически новой командой агенту.
3. До изменения понять причину и согласовать затронутый контракт/ownership. Обычные обратимые детали реализации решать автономно в пределах порученной задачи.
4. Сделать минимальное исправление без несвязанного рефакторинга. Олег не переписывает оптимизатор и SQL/backend за других владельцев.
5. Выполнить релевантную проверку. Для существенного нарушения инварианта добавить негативный regression case.
6. Отметить задачу DONE только после успешной проверки и просмотра изменений. Записать команду, результат и ограничение проверки.
7. Обновить журнал ниже. Исходный отчёт сохранять как исторический снимок; новые результаты добавлять отдельно.

Кандидаты всегда проходят независимый validator. FEASIBLE, timeout и неудачная вставка не доказывают оптимальность или невозможность. Срочность и пробег не должны скрыто менять официальный приоритет coverage → day-active engineers.

## Журнал

| Дата | Работа | Результат | Изменение кода |
|---|---|---|---|
| 2026-09-18 | Архитектурный, доменный, planner, replanning, quality и security аудит | Итог: YES, AFTER P0 FIXES; подробности в REPORT | Нет |
| 2026-09-18 | Tests, Ruff, mypy, миграции, startup, PostgreSQL flow, отдельные эксперименты | Результаты и ограничения в VERIFICATION | Нет |
| 2026-09-18 | Сохранение аудита по просьбе Олега | Добавлена эта папка документации; исправления не начаты | Нет |
| 2026-09-18 | Пользователь уточнил документ про работу с AI | Подтверждён BMad PDF; добавлен WORKFLOW с источниками по страницам | Нет |
| 2026-09-19 | Начато P0-04 | Усилены доказуемые инварианты validator; task остаётся IN_PROGRESS до residual-state boundary | Да; 27 tests passed, Ruff/mypy passed |
| 2026-09-19 | Завершено P1-02 | UUID события материализуется до outbox/audit; добавлена HTTP regression-проверка | Да; 27 tests passed, Ruff/mypy passed |
| 2026-09-19 | Завершено P1-05 | Некорректные дата и окно дают контролируемый 422 | Да; 28 tests passed, Ruff/mypy passed |
| 2026-09-19 | Завершено P1-11 | Недоверенные строки XLSX экспортируются как текст | Да; 28 tests passed, Ruff/mypy passed |
| 2026-09-19 | Завершено P1-10 | HTTPX/HTTPCore не записывают URL с ключами на INFO-уровне | Да; 29 tests passed, Ruff/mypy passed |

Следующий предлагаемый шаг: P0-01/P0-02 — residual-контракт и спорные правила. Наличие этого предложения не запускает реализацию автоматически.
