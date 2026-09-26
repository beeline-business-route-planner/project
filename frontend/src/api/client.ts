import type { ApiErrorBody } from "./types";

const configuredApiUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";
// Local Vite proxy avoids a browser CORS failure when backend has no cors.origins.
const API_BASE_URL = import.meta.env.DEV && /^https?:\/\/(localhost|127\.0\.0\.1):8000\/api(?:\/v1)?\/?$/.test(configuredApiUrl)
  ? "/api"
  : configuredApiUrl.replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  code: string;
  correlationId: string;
  details: Record<string, unknown>;

  constructor(status: number, body: Partial<ApiErrorBody>, requestId?: string | null) {
    const detail = body.detail;
    const detailMessage = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg).filter(Boolean).join("; ")
        : undefined;
    super(body.message ?? detailMessage ?? `Backend вернул HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code ?? "unknown_error";
    this.correlationId = body.correlation_id ?? requestId ?? "—";
    this.details = body.details ?? {};
  }
}

interface ApiOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  rawBody?: BodyInit;
}

export async function apiRequest<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Correlation-ID", crypto.randomUUID());

  let body = options.rawBody;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    body,
  });

  if (!response.ok) {
    let errorBody: Partial<ApiErrorBody> = {};
    try {
      errorBody = (await response.json()) as Partial<ApiErrorBody>;
    } catch {
      errorBody = { message: response.statusText };
    }
    throw new ApiError(response.status, errorBody, response.headers.get("X-Request-Id"));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiBlob(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "X-Correlation-ID": crypto.randomUUID() },
  });
  if (!response.ok) {
    let errorBody: Partial<ApiErrorBody> = {};
    try {
      errorBody = (await response.json()) as Partial<ApiErrorBody>;
    } catch {
      errorBody = { message: response.statusText };
    }
    throw new ApiError(response.status, errorBody, response.headers.get("X-Request-Id"));
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "report";
  return { blob: await response.blob(), filename };
}

export { API_BASE_URL };
