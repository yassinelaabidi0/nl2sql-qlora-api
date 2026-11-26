import type {
  HealthResponse,
  HistoryResponse,
  QueryResponse,
  SchemaResponse,
} from "../types/api";

export type {
  ColumnInfo,
  HealthResponse,
  HistoryEntry,
  HistoryResponse,
  QueryResponse,
  SchemaResponse,
  TableSchema,
} from "../types/api";

interface RawErrorDetail {
  error?: unknown;
  reason?: unknown;
  generated_sql?: unknown;
  sql?: unknown;
}

export class ApiError extends Error {
  status: number;
  errorCode: string;
  reason: string;
  generatedSql?: string;

  constructor(status: number, errorCode: string, reason: string, generatedSql?: string) {
    super(reason);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
    this.reason = reason;
    this.generatedSql = generatedSql;
  }
}

const API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api").replace(
  /\/+$/,
  "",
);

async function parseErrorResponse(res: Response): Promise<ApiError> {
  let errorCode = res.status === 403 ? "forbidden" : "request_failed";
  let reason = res.statusText || `HTTP ${res.status}`;
  let generatedSql: string | undefined;

  try {
    const payload = (await res.json()) as { detail?: unknown; error?: unknown; reason?: unknown };
    const detail = payload?.detail ?? payload;

    if (typeof detail === "string") {
      reason = detail;
    } else if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item ? String(item.msg) : String(item),
        )
        .filter(Boolean);
      if (messages.length > 0) {
        errorCode = "validation_error";
        reason = messages.join("; ");
      }
    } else if (detail && typeof detail === "object") {
      const obj = detail as RawErrorDetail;
      if (typeof obj.error === "string" && obj.error.trim()) {
        errorCode = obj.error;
      }
      if (typeof obj.reason === "string" && obj.reason.trim()) {
        reason = obj.reason;
      }
      if (typeof obj.generated_sql === "string" && obj.generated_sql.trim()) {
        generatedSql = obj.generated_sql;
      } else if (typeof obj.sql === "string" && obj.sql.trim()) {
        generatedSql = obj.sql;
      }
    }
  } catch {
    // Non-JSON error body falls back to HTTP status text.
  }

  return new ApiError(res.status, errorCode, reason, generatedSql);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      0,
      "network_error",
      "Unable to reach the FastAPI service. Ensure the backend is running and reachable.",
    );
  }

  if (!res.ok) {
    throw await parseErrorResponse(res);
  }

  return (await res.json()) as T;
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { method: "GET", signal });
}

export function fetchSchema(signal?: AbortSignal): Promise<SchemaResponse> {
  return request<SchemaResponse>("/schema", { method: "GET", signal });
}

export function fetchHistory(limit = 25, signal?: AbortSignal): Promise<HistoryResponse> {
  return request<HistoryResponse>(`/history?limit=${encodeURIComponent(String(limit))}`, {
    method: "GET",
    signal,
  });
}

export function runQuery(
  question: string,
  schemaDdl?: string,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  const body = schemaDdl ? { question, schema_ddl: schemaDdl } : { question };
  return request<QueryResponse>("/query", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}
