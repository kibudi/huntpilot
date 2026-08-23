import type {
  Application,
  ApplicationCreate,
  Posting,
  PostingStatus,
  Profile,
  Status,
  SweepRun,
} from "./types";

/**
 * A failed request, carrying the status code alongside the message.
 *
 * The code is kept because not every rejection is a failure to the caller: tracking a posting the
 * API already holds comes back 409, and that is the state the user asked for rather than an
 * error. Deciding that by matching the message text would break the moment the wording changes.
 */
export class ApiError extends Error {
  status: number;
  /**
   * FastAPI's `detail` exactly as it arrived, for callers that need more than one sentence.
   *
   * The message above is the first complaint flattened for display, which is all most callers
   * want. A form editing sixty patterns wants all of them, and attached to the right field, so the
   * raw value is kept rather than reconstructed from the message afterwards.
   */
  detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Calls the API and returns the raw response, throwing on any non-2xx.
 *
 * FastAPI reports validation failures as 422 with a `detail` array; the first entry's message is
 * surfaced so a rejected write says why rather than showing a bare status code.
 *
 * The body is deliberately left unread: `DELETE` answers 204 with no body at all, and calling
 * `.json()` on that throws a `SyntaxError` that would surface as a failure for a request that
 * actually succeeded.
 */
async function send(path: string, init?: RequestInit): Promise<Response> {
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
    throw new ApiError(message, response.status, detail);
  }

  return response;
}

/** Calls the API and returns the parsed body. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await (await send(path, init)).json()) as T;
}

/** Fetches every tracked application, most recently updated first. */
export function listApplications(): Promise<Application[]> {
  return request<Application[]>("/api/applications");
}

/**
 * Fetches swept board postings, newest-discovered first.
 *
 * `status` narrows the list to open or closed postings; omitting it returns both. The board tab
 * omits it deliberately — one request for everything lets the open/closed/all chips carry live
 * counts and switch between them without a second round trip.
 */
export function listPostings(status?: PostingStatus): Promise<Posting[]> {
  const query = status ? `?status=${status}` : "";
  return request<Posting[]>(`/api/postings${query}`);
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

/**
 * Removes one application permanently.
 *
 * Returns nothing: the API answers 204 with an empty body, so there is no response to parse and
 * no document left to hand back.
 */
export async function deleteApplication(id: string): Promise<void> {
  await send(`/api/applications/${id}`, { method: "DELETE" });
}

/**
 * Starts one sweep of the watchlist.
 *
 * Answers as soon as the run is recorded, not when the pass is over — a sweep reads a few dozen
 * boards and takes minutes. The run comes back in its running state with no summary, which is what
 * gives the panel something to poll for from the first moment.
 *
 * A 409 is left to the caller to interpret rather than treated as a failure here: it means a sweep
 * is already going, which is the state the user asked for.
 */
export function startSweep(): Promise<SweepRun> {
  return request<SweepRun>("/api/sweeps", { method: "POST" });
}

/**
 * Returns every recorded sweep, most recently started first.
 *
 * The whole history rather than a page of it, because sweeps run four times a day and the list is
 * a few hundred small records a year. It is also how the panel watches a running sweep: the run
 * being polled is the first entry.
 */
export function fetchSweeps(): Promise<SweepRun[]> {
  return request<SweepRun[]>("/api/sweeps");
}

/**
 * Returns the search every sweep is currently run against.
 *
 * Never a 404: a database that has never been swept still answers, because the committed file
 * seeds one on first read. An editor that could not load until something had saved a profile would
 * have no way to save the first one.
 */
export function fetchProfile(): Promise<Profile> {
  return request<Profile>("/api/profile");
}

/**
 * Replaces the stored search profile and returns it as stored.
 *
 * A replacement rather than a patch, because the fields are not independent — which families are
 * tried in which order, and which technologies count as known against which count as unknown, only
 * mean anything as a set.
 *
 * What comes back is the normalised profile rather than an echo, so the caller can show what the
 * filters will actually use instead of what was typed.
 */
export function saveProfile(profile: Profile): Promise<Profile> {
  return request<Profile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}
