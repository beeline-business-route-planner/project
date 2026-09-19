# Frontend integration contract

Backend and frontend communicate over JSON HTTP. CORS does not transport data; it permits a
browser application from an explicitly configured origin to call the API.

## Development URLs

- API base URL: `http://localhost:8000/api/v1`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI 3 schema: `http://localhost:8000/openapi.json`
- Liveness: `GET /api/v1/health`
- PostgreSQL readiness: `GET /api/v1/readiness`

The frontend should keep the base URL in its own environment variable, for example
`VITE_API_BASE_URL=http://localhost:8000/api/v1`. Do not put the 2GIS key in frontend code: all
calls to 2GIS are server-to-server.

## CORS

Allowed browser origins are configured by `CORS_ORIGINS`. An origin contains scheme, host and
port and must match exactly; paths are not allowed. Defaults cover Vite and common React dev
servers:

```dotenv
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
CORS_ALLOW_CREDENTIALS=false
CORS_ALLOW_METHODS=GET,POST,PATCH,OPTIONS
CORS_ALLOW_HEADERS=Content-Type,Idempotency-Key,X-Correlation-ID
CORS_EXPOSE_HEADERS=X-Correlation-ID,Content-Disposition
CORS_MAX_AGE=600
```

The list settings accept either comma-separated values or a JSON array. Add the deployed frontend
origin explicitly in production. Do not use `*` together with credentials.

## Recommended first-screen flow

1. `GET /scenarios` and select a scenario plus `planning_date`.
2. `GET /plans?scenario_id=...&planning_date=YYYY-MM-DD` and select the approved plan.
   Load requests and engineers through their list endpoints as needed.
3. If there is no plan, import a geocoded dataset, call `POST /plans/run`, and approve the draft.
4. `GET /plans/{plan_id}/routes` loads overview geometry for every engineer. Coordinates are
   `[longitude, latitude]`; empty routes have `geometry=null` and `route_status="empty"`.
5. On engineer selection, request `GET /plans/{plan_id}/engineers/{engineer_id}/route` and display
   its detailed geometry. Keep responses by plan ID, revision and engineer ID.
6. Use `GET /plans/diff` before approving a proposed replan. The new plan has a different ID;
   old saved routes stay unchanged.

The existing dashboard and full-plan endpoints remain compatible and include detailed geometry;
using those large responses for the map would lose the payload benefit of overview. All route GETs
read saved PostgreSQL/Dragonfly data without routing calls. A legacy plan without new artifacts returns
`409 route_artifacts_unavailable` on the new endpoints; offer explicit creation of a new plan.
Contract details and backend demo commands: [ROUTING.md](ROUTING.md). This change supplies backend
API support; it does not implement a frontend map.

All timestamps are ISO 8601. Send timestamps with an explicit UTC offset, for example
`2026-08-17T10:00:00+03:00`. Identifiers are UUID strings.

## Mutating requests

- `POST /imports` accepts `multipart/form-data` with field `file`; pass `Idempotency-Key`.
- `POST /requests` creates a request and starts one replanning proposal.
- `POST /requests/{id}/facts` records a confirmed manual fact.
- `POST /events` records a day event and starts one replanning proposal.
- `POST /plans/{id}/manual-change` creates a new draft; it never mutates the old plan.
- `POST /plans/{id}/approve` requires the expected active base plan and can return `409` when the
  proposal is stale.

The frontend should disable repeated submit while a mutation is in flight and reuse the same
idempotency key when retrying the same logical action.

## Errors and tracing

Domain and request-validation errors use one shape:

```json
{
  "code": "stale_base_plan",
  "message": "The active plan changed after this draft was calculated",
  "details": {},
  "correlation_id": "a7fcda41-9dca-4d64-8338-7c1ecaa8db91"
}
```

- `404`: object not found;
- `409`: optimistic-lock/state conflict;
- `422`: invalid request or domain operation;
- `503`: geocoder, router or another external dependency is unavailable.

Send `X-Correlation-ID` when available. Otherwise the backend generates one and exposes it to
browser JavaScript in the response header. Display the ID in an error-details panel so backend and
frontend logs can be correlated.

## Reports

`GET /plans/{plan_id}/reports/xlsx` and `/pdf` return binary downloads. Read the filename from
`Content-Disposition`, which is exposed by CORS. In browser code use `response.blob()` instead of
trying to parse the response as JSON.

## Type generation

The OpenAPI responses are typed. A frontend can generate TypeScript without copying interfaces by
hand, for example:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
```

Regenerate the client whenever the backend OpenAPI schema changes.
