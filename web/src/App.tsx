import { useEffect, useMemo, useState } from "react";
import { createApplication, listApplications, updateApplication } from "./api";
import { AddApplicationDialog } from "./components/AddApplicationDialog";
import {
  ApplicationsTable,
  sortApplications,
  type Sort,
} from "./components/ApplicationsTable";
import { Toolbar, type StatusFilter } from "./components/Toolbar";
import { today } from "./format";
import type { DialogState, LoadState, RowState } from "./state";
import {
  STATUSES,
  type Application,
  type ApplicationCreate,
  type Status,
} from "./types";

/** The dashboard. One screen: every tracked application, filterable and editable in place. */
export default function App() {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [dialog, setDialog] = useState<DialogState>({ kind: "closed" });
  const [rowStates, setRowStates] = useState<Record<string, RowState>>({});
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>(null);
  const [sort, setSort] = useState<Sort>({
    key: "updated_at",
    ascending: false,
  });

  useEffect(() => {
    let cancelled = false;

    listApplications()
      .then((applications) => {
        if (!cancelled) setLoad({ kind: "ready", applications });
      })
      .catch((error: Error) => {
        if (!cancelled) setLoad({ kind: "error", message: error.message });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const applications = load.kind === "ready" ? load.applications : [];

  const counts = useMemo(() => {
    const tally = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Record<
      Status,
      number
    >;
    for (const application of applications) tally[application.status] += 1;
    return tally;
  }, [applications]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matched = applications.filter((application) => {
      const matchesFilter = filter === null || application.status === filter;
      const matchesQuery =
        needle === "" ||
        application.company.toLowerCase().includes(needle) ||
        application.role.toLowerCase().includes(needle);
      return matchesFilter && matchesQuery;
    });
    return sortApplications(matched, sort);
  }, [applications, filter, query, sort]);

  /** Replaces one application in state, leaving the rest untouched. */
  function replace(updated: Application) {
    setLoad((current) =>
      current.kind === "ready"
        ? {
            ...current,
            applications: current.applications.map((application) =>
              application.id === updated.id ? updated : application,
            ),
          }
        : current,
    );
  }

  /**
   * Moves an application to a new status.
   *
   * The change is applied locally first so the pill responds immediately, and rolled back if the
   * write fails.
   *
   * Moving out of `saved` into a stage that implies the application was sent stamps today's date.
   * `rejected` and `ghosted` are excluded: a saved posting can be abandoned without ever being
   * applied to, and stamping those would invent history the tracker then reports as fact.
   */
  async function changeStatus(application: Application, next: Status) {
    const changes: { status: Status; applied_date?: string } = { status: next };
    const impliesSent: Status[] = ["applied", "interview", "offer"];
    if (
      application.status === "saved" &&
      impliesSent.includes(next) &&
      !application.applied_date
    ) {
      changes.applied_date = today();
    }

    const previous = application;
    replace({ ...application, ...changes });
    setRowStates((current) => ({
      ...current,
      [application.id]: { kind: "saving" },
    }));

    try {
      replace(await updateApplication(application.id, changes));
      setRowStates((current) => ({
        ...current,
        [application.id]: { kind: "idle" },
      }));
    } catch (error) {
      replace(previous);
      setRowStates((current) => ({
        ...current,
        [application.id]: { kind: "failed", message: (error as Error).message },
      }));
    }
  }

  /** Clears a row's error message, which otherwise stays pinned to the row for the whole session. */
  function dismissError(id: string) {
    setRowStates((current) => ({ ...current, [id]: { kind: "idle" } }));
  }

  /** Creates an application and puts it at the top, where the newest-updated sort would place it. */
  async function add(payload: ApplicationCreate) {
    setDialog({ kind: "submitting" });
    try {
      const created = await createApplication(payload);
      setLoad((current) =>
        current.kind === "ready"
          ? { ...current, applications: [created, ...current.applications] }
          : current,
      );
      setDialog({ kind: "closed" });
    } catch (error) {
      setDialog({ kind: "failed", message: (error as Error).message });
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-[1400px] flex-col px-8 pt-7 pb-10">
      <header className="flex items-end justify-between gap-6 border-b border-line pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-3.5 w-3.5 rounded-[3px] bg-accent" />
            <h1 className="font-display text-lg font-extrabold tracking-tight">
              huntpilot
            </h1>
          </div>
          <p className="mt-1 text-xs text-ink-dim">
            Every application, and what needs chasing.
          </p>
        </div>

        <div className="flex gap-7">
          <Stat label="Tracked" value={applications.length} />
          <Stat label="Active" value={counts.applied + counts.interview} />
          <Stat label="Interviews" value={counts.interview} />
          <Stat label="Offers" value={counts.offer} />
        </div>
      </header>

      <Toolbar
        query={query}
        onQueryChange={setQuery}
        filter={filter}
        onFilterChange={setFilter}
        counts={counts}
        total={applications.length}
        onAdd={() => setDialog({ kind: "open" })}
      />

      {load.kind === "loading" && <Notice>Loading…</Notice>}

      {load.kind === "error" && (
        <Notice tone="danger">
          Could not reach the API — {load.message}. Is the backend running on
          port 8000?
        </Notice>
      )}

      {load.kind === "ready" && (
        <ApplicationsTable
          applications={visible}
          sort={sort}
          onSortChange={setSort}
          rowStates={rowStates}
          onStatusChange={changeStatus}
          onDismissError={dismissError}
          onAdd={() => setDialog({ kind: "open" })}
          emptyMessage={
            applications.length === 0
              ? "Nothing tracked yet."
              : "No applications match this filter."
          }
        />
      )}

      <AddApplicationDialog
        state={dialog}
        onClose={() => setDialog({ kind: "closed" })}
        onSubmit={add}
        onInvalid={(message) => setDialog({ kind: "invalid", message })}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <div className="font-mono text-[22px] leading-none font-medium">
        {value}
      </div>
      <div className="mt-1 text-[11px] tracking-[0.04em] text-ink-dim uppercase">
        {label}
      </div>
    </div>
  );
}

function Notice({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "danger";
}) {
  return (
    <div
      className={`rounded-lg border border-line bg-panel px-4 py-10 text-center text-[13px] ${
        tone === "danger" ? "text-danger" : "text-ink-dim"
      }`}
    >
      {children}
    </div>
  );
}
