import type { Application, Posting } from "./types";

/** Which tab the dashboard is showing. */
export type Tab = "applications" | "board";

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
 * The board tab's load state.
 *
 * `idle` is the one case the applications list has no use for: the board is a second dataset from
 * a second endpoint, and a user who only came to update a status never looks at it. So it is
 * fetched the first time the tab is opened rather than on page load, and `idle` is what marks the
 * fetch as not yet asked for.
 *
 * Once loaded the postings stay in state for the session. Switching tabs is then free, and the
 * search and filters a user set on the board survive a trip to the applications list.
 */
export type BoardState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; postings: Posting[] };

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
 * The state of the track button on one board row.
 *
 * `tracked` is the terminal case rather than a return to `idle`: once a posting is in the
 * pipeline the button stops being a button, so the row needs to remember that within the session
 * even when the write that proved it never reached the applications list — which is what a 409
 * on an already-tracked url leaves behind.
 */
export type TrackState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "tracked" }
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
