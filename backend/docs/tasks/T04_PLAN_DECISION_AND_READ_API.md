# T04. Approve/reject и API чтения планов

## Цель

Реализовать lifecycle решения диспетчера и привести current/history/detail к согласованной
семантике.

## Исполнитель и зависимости

- Исполнитель: Backend B.
- Требует: G01.
- Параллельно: T03 и алгоритмическая дорожка.
- Блокирует: G02.

## HTTP API

- `POST /api/plans/{plan_id}/approve`;
- `POST /api/plans/{plan_id}/reject`;
- `GET /api/plans/current?region=...&planning_date=...`;
- `GET /api/plans?region=...`;
- `GET /api/plans/{plan_id}`.

## Approve

В одной транзакции и с row lock:

1. загрузить plan;
2. потребовать `pending`;
3. проверить рабочий день;
4. для replan/event replan убедиться, что `based_on_plan_id` всё ещё current;
5. проверить отсутствие нового approved event после расчёта;
6. проверить версии затрагиваемых request/status/engineer availability;
7. убедиться, что изменяемые кандидатом stops не оказались в прошлом;
8. для initial применить согласованный validity policy;
9. перевести кандидата в approved;
10. перевести все остальные pending plans этого region/day в rejected;
11. для event plan синхронно изменить status события;
12. commit.

Пока более точное правило initial validity не согласовано, применяется только явно
конфигурируемый fallback 10 минут. Значение не зашивается литералом. API/validator должны
позволять заменить policy без изменения route.

## Reject

- разрешён только для pending;
- идемпотентное повторное решение не маскирует ошибку состояния;
- event plan отклоняет связанное pending-событие в той же транзакции;
- rejected никогда нельзя approve.

## Read API

- current — последний по `approved_at` approved указанного региона/дня;
- list — сортировка `created_at DESC`, status виден всегда;
- detail — полный snapshot G01 и вычисленный diff;
- после decision frontend может перечитать список и увидеть автоматически rejected
  siblings;
- initial имеет `diff = null`.

## Конкурентность

Два одновременных approve одного региона/дня не могут создать два current. Проигравший
запрос получает domain conflict после повторной проверки под lock.

## Не входит

- force approve;
- пользовательское время события;
- отдельный diff endpoint;
- новые фильтры кроме обязательного region;
- алгоритмическая проверка маршрута.

## Критерии приёмки

1. Pending не является current.
2. Approve делает его current и отклоняет все более старые/новые pending siblings.
3. Reject не меняет current.
4. Нельзя approve rejected или план со сменившейся base.
5. Конкурентные решения сериализуются.
6. Все ответы используют единый формат ошибок и статусов.
7. `make check` проходит.
