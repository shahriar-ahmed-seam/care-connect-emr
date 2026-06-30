export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

export const API_V1 = `${API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  code: string;
  field?: string;
  status: number;

  constructor(code: string, message: string, status: number, field?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.field = field;
    this.status = status;
  }
}

export class ServiceUnavailableError extends Error {
  constructor(message = "Service temporarily unavailable") {
    super(message);
    this.name = "ServiceUnavailableError";
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
}

/**
 * Perform an API request and return the parsed JSON body.
 *
 * Throws {@link ApiError} for handled backend errors (4xx with the error
 * envelope) and {@link ServiceUnavailableError} for network failures or 5xx
 * responses so the UI can present a retry affordance (Req 21.4).
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, token, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_V1}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch {
    // Network error / backend unreachable.
    throw new ServiceUnavailableError();
  }

  if (response.status >= 500) {
    throw new ServiceUnavailableError();
  }

  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const envelope = (payload as { error?: { code: string; message: string; field?: string } } | null)
      ?.error;
    if (envelope) {
      throw new ApiError(
        envelope.code,
        envelope.message,
        response.status,
        envelope.field,
      );
    }
    throw new ApiError("unknown_error", "Something went wrong.", response.status);
  }

  return payload as T;
}

/** Download binary content (e.g. a prescription PDF) as a Blob. */
export async function apiDownload(
  path: string,
  token?: string | null,
): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_V1}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
  } catch {
    throw new ServiceUnavailableError();
  }
  if (response.status >= 500) throw new ServiceUnavailableError();
  if (!response.ok) {
    throw new ApiError("download_failed", "Could not download the file.", response.status);
  }
  return response.blob();
}
