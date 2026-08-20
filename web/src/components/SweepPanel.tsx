import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchSweeps, startSweep } from "../api";
import { exactTime, relativeTime } from "../format";
import type { HistoryState, SweepState } from "../state";
import { ProfileForm } from "./ProfileForm";
import type { BoardFailure, SweepRun, SweepState as RunState } from "../types";

/** How often a running sweep is polled for, in milliseconds. */
const POLL_INTERVAL = 3000;

/**
 * How each recorded outcome is labelled and coloured.
 *
 * A lookup rather than a chain of conditionals so that adding a state to the backend enum shows
 * up here as a type error rather than as a run that silently renders unstyled.
 */
const RUN_LOOK: Record<RunState, { label: string; className: string }> = {
  running: { label: "Running", className: "bg-accent text-on-accent" },
  completed: { label: "Completed", className: "bg-chip text-ink" },
  failed: { label: "Failed", className: "bg-danger text-page" },
  abandoned: { label: "Abandoned", className: "bg-ink/15 text-ink-dim" },
};

/** The states a run is no longer moving out of. */
const SETTLED: RunState[] = ["completed", "failed", "abandoned"];

/**
 * The sweep tab: a button that starts a pass, the pass being watched, and the history.
 *
 * Every decision about a sweep belongs to the API — whether one may start, when it is over, what
 * it found. This component starts one, polls, and renders what comes back; it never infers an
 * outcome from elapsed time, because a slow sweep and a dead one look identical from here and only
 * the server knows which it is.
 *
 * ``onSwept`` fires when a watched pass reaches a final state, because the postings the board tab
 * is holding were read before it ran and are now behind.
 */
export function SweepPanel({ onSwept }: { onSwept: () => void }) {
  const [sweep, setSweep] = useState<SweepState>({ kind: "idle" });
  const [history, setHistory] = useState<HistoryState>({ kind: "idle" });

  /**
   * Holds the run being watched for the poll callback.
   *
   * The interval is set up once per running sweep, so without this the closure would capture the
   * first render's state and keep comparing against a run id that has since changed.
   */
  const watching = useRef<string | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      const runs = await fetchSweeps();
      setHistory({ kind: "ready", runs });
      return runs;
    } catch (error) {
      setHistory({
        kind: "error",
        message: error instanceof Error ? error.message : "Unknown error",
      });
      return null;
    }
  }, []);

  useEffect(() => {
    setHistory({ kind: "loading" });
    void loadHistory();
  }, [loadHistory]);

  /**
   * Adopts a sweep that was already running when the tab was opened.
   *
   * The scheduled sweep runs whether anyone is watching or not, so a freshly loaded panel that
   * showed `idle` next to a history row saying `running` would be contradicting itself. Runs only
   * from `idle`, so it can never pull the panel back off a sweep the user just started.
   */
  useEffect(() => {
    if (sweep.kind !== "idle" || history.kind !== "ready") return;
    const live = history.runs.find((run) => run.state === "running");
    if (live) setSweep({ kind: "running", runId: live.id });
  }, [sweep.kind, history]);

  /**
   * Polls the history while a sweep is running, and stops the moment it settles.
   *
   * The run being watched is looked up by id rather than taken from the top of the list, because
   * the scheduled sweep can record a newer one while this is going and the panel must keep
   * reporting the pass it started. A watched run that has vanished from the history is treated as
   * finished rather than polled for ever.
   */
  useEffect(() => {
    if (sweep.kind !== "running") return;
    watching.current = sweep.runId;

    const timer = setInterval(async () => {
      const runs = await loadHistory();
      if (!runs) return;
      const run = runs.find((candidate) => candidate.id === watching.current);
      if (!run) {
        setSweep({ kind: "idle" });
        return;
      }
      if (!SETTLED.includes(run.state)) return;
      setSweep({ kind: "finished", run });
      onSwept();
    }, POLL_INTERVAL);

    return () => clearInterval(timer);
  }, [sweep, loadHistory, onSwept]);

  /**
   * Asks the API to start a sweep.
   *
   * A 409 becomes `refused` rather than an error: it means a sweep is already going, which is what
   * the user wanted to be true. The history is reloaded so the pass already under way is picked up
   * and watched, which is what turns the refusal into something the panel can follow.
   *
   * When that reload finds nothing running the panel returns to `idle`, because the blocking sweep
   * can finish in the moment between the refusal and the reload. Staying on `refused` would leave
   * "a sweep is already running" on screen beside a button that works, contradicting itself until
   * something else happened to move the panel.
   */
  async function run() {
    setSweep({ kind: "starting" });
    try {
      const started = await startSweep();
      setSweep({ kind: "running", runId: started.id });
      void loadHistory();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setSweep({ kind: "refused", message: error.message });
        const runs = await loadHistory();
        const live = runs?.find((candidate) => candidate.state === "running");
        setSweep(live ? { kind: "running", runId: live.id } : { kind: "idle" });
        return;
      }
      setSweep({
        kind: "failed",
        message: error instanceof Error ? error.message : "Unknown error",
      });
    }
  }

  const busy = sweep.kind === "starting" || sweep.kind === "running";

  return (
    <section className="flex flex-col gap-6">
      <div className="rounded-lg border border-line bg-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-display text-lg text-ink">Sweep the watchlist</h2>
            <p className="mt-1 text-sm text-ink-dim">
              Reads every watched board and records what changed. Takes a few minutes.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void run()}
            disabled={busy}
            className="rounded-md bg-accent px-4 py-2 font-medium text-on-accent transition hover:bg-accent-bright disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? "Sweeping…" : "Run a sweep"}
          </button>
        </div>

        <SweepStatus state={sweep} />
      </div>

      <div>
        <h2 className="font-display text-lg text-ink">History</h2>
        <HistoryList state={history} />
      </div>

      <ProfileForm />
    </section>
  );
}

/**
 * The line under the button saying where the current attempt got to.
 *
 * Renders nothing at all when idle, so the panel is quiet until something has been asked of it.
 */
function SweepStatus({ state }: { state: SweepState }) {
  if (state.kind === "idle") return null;

  if (state.kind === "starting") {
    return <Note tone="dim">Starting…</Note>;
  }

  if (state.kind === "running") {
    return <Note tone="accent">A sweep is running. This panel updates itself.</Note>;
  }

  if (state.kind === "refused") {
    return <Note tone="dim">{state.message}</Note>;
  }

  if (state.kind === "failed") {
    return <Note tone="danger">Could not start a sweep — {state.message}</Note>;
  }

  const { run } = state;
  if (run.state === "completed" && run.summary) {
    return (
      <Note tone="dim">Finished {relativeTime(run.finished_at ?? run.started_at)}.</Note>
    );
  }
  return (
    <Note tone="danger">
      {run.state === "abandoned"
        ? "The sweep stopped without finishing."
        : `The sweep failed — ${run.error ?? "no reason recorded"}`}
    </Note>
  );
}

/** One line of feedback under the run button. */
function Note({
  tone,
  children,
}: {
  tone: "dim" | "accent" | "danger";
  children: React.ReactNode;
}) {
  const colour =
    tone === "danger"
      ? "text-danger-ink"
      : tone === "accent"
        ? "text-accent-ink"
        : "text-ink-dim";
  return <p className={`mt-4 text-sm ${colour}`}>{children}</p>;
}

/** The recorded sweeps, newest first. */
function HistoryList({ state }: { state: HistoryState }) {
  if (state.kind === "idle" || state.kind === "loading") {
    return <p className="mt-3 text-sm text-ink-dim">Loading…</p>;
  }
  if (state.kind === "error") {
    return <p className="mt-3 text-sm text-danger-ink">Could not load the history — {state.message}</p>;
  }
  if (state.runs.length === 0) {
    return (
      <p className="mt-3 text-sm text-ink-dim">
        No sweeps recorded yet. Run one, or wait for the scheduled pass.
      </p>
    );
  }

  return (
    <ul className="mt-3 flex flex-col gap-2">
      {state.runs.map((run) => (
        <HistoryRow key={run.id} run={run} />
      ))}
    </ul>
  );
}

/**
 * One recorded sweep.
 *
 * The counts are shown only for a run that produced a summary. A failed or abandoned run has none,
 * and rendering zeros for it would claim the sweep looked at every board and found nothing.
 */
function HistoryRow({ run }: { run: SweepRun }) {
  const look = RUN_LOOK[run.state];
  return (
    <li className="rounded-md border border-line bg-panel px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${look.className}`}>
          {look.label}
        </span>
        <span className="text-sm text-ink" title={exactTime(run.started_at)}>
          {relativeTime(run.started_at)}
        </span>
        <span className="text-sm text-ink-dim">{duration(run)}</span>
      </div>

      {run.summary && (
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-dim">
          <Count label="boards" value={run.summary.boards_swept} />
          <Count label="added" value={run.summary.added} />
          <Count label="still open" value={run.summary.still_open} />
          <Count label="closed" value={run.summary.closed} />
          <Count label="reopened" value={run.summary.reopened} />
          {run.summary.boards_failed > 0 && (
            <span className="text-danger-ink">{run.summary.boards_failed} boards failed</span>
          )}
        </div>
      )}

      {run.error && <p className="mt-2 text-sm text-danger-ink">{run.error}</p>}

      {run.summary && run.summary.failures.length > 0 && <Failures failures={run.summary.failures} />}
    </li>
  );
}

/** One labelled number from a sweep summary. */
function Count({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <span className="text-ink">{value}</span> {label}
    </span>
  );
}

/**
 * The boards that could not be read, behind a disclosure.
 *
 * Collapsed by default because a sweep that failed on two boards out of twenty-eight is a normal
 * sweep, and listing them beside the counts every time would make the usual case look broken.
 */
function Failures({ failures }: { failures: BoardFailure[] }) {
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-sm text-accent-ink">
        {failures.length} board{failures.length === 1 ? "" : "s"} could not be read
      </summary>
      <ul className="mt-2 flex flex-col gap-1 text-sm text-ink-dim">
        {failures.map((failure) => (
          <li key={`${failure.ats}:${failure.token}`}>
            <span className="text-ink">{failure.name}</span> — {failure.error}
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * How long a run took, or how long it has been going.
 *
 * A run still going is measured against now so the number moves while it is watched; a finished
 * one is measured between its own two timestamps, which is fixed for ever.
 */
function duration(run: SweepRun): string {
  const start = new Date(run.started_at).getTime();
  const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "";

  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
