# G02. Интеграционный барьер initial end-to-end

## Цель

Собрать T03, T04, A01 и A02 в полностью работающий пользовательский сценарий initial.

## Входы и исполнитель

- Требует: T03, T04, A01, A02.
- Исполнитель: Backend A.
- Backend B: ревью lifecycle/concurrency/API.
- Algorithm: ревью адаптера и результатов расчёта.
- Блокирует: T05 и T06.

## Интеграционные работы

1. Соединить normalized import snapshot с pure initial/baseline API.
2. Удалить временные adapters и двойное сохранение Plan.
3. Проверить одну транзакционную точку сохранения результата на регион.
4. Проверить карточку pending initial, `diff = null`, baseline metrics.
5. Проверить approve/reject и автоматический reject siblings.
6. Проверить запрет нового Excel после approved initial.
7. Проверить current за правильный region/day.
8. Убедиться, что временный initial validity fallback конфигурируется и локализован в
   policy, а не размазан по router/service/frontend DTO.

## Обязательные сценарии

- один округ: generate → pending → approve → current;
- generate → reject → current отсутствует;
- два pending initial → approve второго → первый rejected;
- три округа, один падает → partial success двух;
- повторный upload до approve разрешён;
- повторный upload после approve запрещён;
- расчёт после начала смены учитывает cutoff;
- конкурентный approve не создаёт два current.

## Критерии приёмки

1. Все сценарии проходят на БД, поднятой с нуля.
2. Algorithm не пишет БД, backend не повторяет алгоритмическую логику.
3. API соответствует `user-case/BACKEND.md`.
4. Нет старого `is_baseline` и `manual_replan` в публичной модели.
5. `make check` проходит.
