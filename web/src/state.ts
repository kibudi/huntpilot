import type { Application } from "./types";

/**
 * The screen's load state.
 *
 * A discriminated union rather than separate `loading`, `error` and `data` values: those allow
 * combinations that cannot happen — loading and errored at once, ready with no data — and every
 * render has to re-derive which one wins. Here exactly one case is true and the compiler knows
 * which fields exist in each.
 */
export type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; applications: Application[] };

/**
 * The state of a write in flight for a single row.
 *
 * Writes are optimistic, so `failed` carries the value to roll back to along with the message.
 */
export type RowState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "failed"; message: string };

/** The add-application dialog. */
export type DialogState =
  | { kind: "closed" }
  | { kind: "open" }
  | { kind: "submitting" }
  | { kind: "invalid"; message: string }
  | { kind: "failed"; message: string };
