import type { Application, ApplicationCreate, Status } from "./types";

/**
 * Calls the API and returns the parsed body.
 *
 * FastAPI reports validation failures as 422 with a `detail` array; the first entry's message is
 * surfaced so a rejected write says why rather than showing a bare status code.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? `${detail[0].loc?.slice(1).join(".") ?? ""} ${detail[0].msg}`.trim()
          : `Request failed (${response.status})`;
    throw new Error(message);
  }

  return (await response.json()) as T;
}

/** Fetches every tracked application, most recently updated first. */
export function listApplications(): Promise<Application[]> {
  return request<Application[]>("/api/applications");
}

/** Tracks a new application. */
export function createApplication(
  payload: ApplicationCreate,
): Promise<Application> {
  return request<Application>("/api/applications", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Changes one application.
 *
 * Only the fields passed are sent, so anything omitted keeps its stored value.
 */
export function updateApplication(
  id: string,
  changes: { status?: Status; applied_date?: string | null; notes?: string },
): Promise<Application> {
  return request<Application>(`/api/applications/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}
