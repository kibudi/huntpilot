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

/**
 * The delete-confirmation dialog.
 *
 * Every case except `closed` carries the application itself rather than its id, so the dialog can
 * name what is about to be destroyed without looking it up in a list that the delete is in the
 * middle of changing.
 */
export type DeleteState =
  | { kind: "closed" }
  | { kind: "confirming"; application: Application }
  | { kind: "deleting"; application: Application }
  | { kind: "failed"; application: Application; message: string };

/** The add-application dialog. */
export type DialogState =
  | { kind: "closed" }
  | { kind: "open" }
  | { kind: "submitting" }
  | { kind: "invalid"; message: string }
  | { kind: "failed"; message: string };
