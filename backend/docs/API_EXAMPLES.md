# Примеры API для фронтенда

## Успешный запуск планирования

```json
{
  "planning_run_id": "1d17f7be-04fb-43da-b70b-313a9384479e",
  "plan_id": "86652afe-6ac7-4e69-9c07-7602dc5fb6f6",
  "status": "succeeded"
}
```

## Ошибка доменного правила

```json
{
  "code": "stale_base_plan",
  "message": "Draft was calculated from a plan that is no longer active",
  "details": {
    "draft_base_plan_id": "...",
    "active_plan_id": "..."
  },
  "correlation_id": "56e03708-3c73-48ca-94e4-cf27a4b8c86f"
}
```

## Неназначенная заявка

```json
{
  "request_id": "7d4421dd-acde-474c-9f43-9a3282a9b04d",
  "request_external_id": "57299",
  "reason_code": "outside_client_window",
  "explanation": "Travel and work do not fully fit in the client window"
}
```

