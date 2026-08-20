import type { Application, Posting, SweepRun } from "./types";

/** Which tab the dashboard is showing. */
export type Tab = "applications" | "board" | "sweep";

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

/**
 * Where the sweep panel is in the cycle of starting a pass and watching it.
 *
 * A state machine rather than a set of booleans because the UI polls: between asking for a sweep
 * and seeing it finish there are several distinct waits, and each one shows something different.
 * Booleans would allow starting-and-finished at once, and every render would have to work out
 * which of them wins.
 *
 * `starting` is the request in flight, before there is a run id to name. `running` begins the
 * moment the API answers with a run and lasts until a poll reports a final state — the API decides
 * when it is over, never a timer here.
 *
 * `refused` is its own case rather than an error. A 409 means a sweep is already going, most often
 * the scheduled one, and that is the state the user wanted rather than a failure of theirs; the
 * next poll turns it into `running` against the pass that was already under way.
 *
 * `failed` is the request to start never landing. A sweep that ran and failed is a `finished` run
 * carrying its own error, because it is a recorded outcome rather than something that went wrong
 * in the browser.
 */
export type SweepState =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "running"; runId: string }
  | { kind: "refused"; message: string }
  | { kind: "finished"; run: SweepRun }
  | { kind: "failed"; message: string };

/**
 * The sweep history's load state.
 *
 * Separate from the run state above because the two answer different questions and fail
 * independently: the history is worth showing even when a sweep could not be started, and a sweep
 * is worth watching even on a first load where the history has not arrived yet.
 */
export type HistoryState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; runs: SweepRun[] };
