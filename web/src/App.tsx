import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createApplication,
  deleteApplication,
  listApplications,
  listPostings,
  updateApplication,
} from "./api";
import { AddApplicationDialog } from "./components/AddApplicationDialog";
import { ConfirmDeleteDialog } from "./components/ConfirmDeleteDialog";
import {
  ApplicationsTable,
  sortApplications,
  type Sort,
} from "./components/ApplicationsTable";
import {
  BoardToolbar,
  type PostingStatusFilter,
} from "./components/BoardToolbar";
import {
  PostingsTable,
  sortPostings,
  type PostingSort,
} from "./components/PostingsTable";
import { SweepPanel } from "./components/SweepPanel";
import { Toolbar, type StatusFilter } from "./components/Toolbar";
import { today } from "./format";
import type {
  BoardState,
  DeleteState,
  DialogState,
  LoadState,
  RowState,
  Tab,
  TrackState,
} from "./state";
import {
  REGIONS,
  STATUSES,
  type Application,
  type ApplicationCreate,
  type Posting,
  type PostingStatus,
  type Region,
  type RegionFilter,
  type Status,
} from "./types";

/**
 * The dashboard. Two tabs over one header: applications tracked by hand, and the board the sweep
 * fills by itself.
 *
 * Both tabs keep their state here rather than inside a tab component, so switching between them
 * never throws away a loaded list or the filters set on it.
 */
export default function App() {
  const [tab, setTab] = useState<Tab>("applications");
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [dialog, setDialog] = useState<DialogState>({ kind: "closed" });
  const [pendingDelete, setPendingDelete] = useState<DeleteState>({
    kind: "closed",
  });
  const [rowStates, setRowStates] = useState<Record<string, RowState>>({});
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StatusFilter>(null);
  const [sort, setSort] = useState<Sort>({
    key: "updated_at",
    ascending: false,
  });

  const [board, setBoard] = useState<BoardState>({ kind: "idle" });
  const [boardQuery, setBoardQuery] = useState("");
  const [region, setRegion] = useState<RegionFilter>(null);
  const [postingStatus, setPostingStatus] =
    useState<PostingStatusFilter>("open");
  const [boardSort, setBoardSort] = useState<PostingSort>({
    key: "first_seen_at",
    ascending: false,
  });
  const [trackStates, setTrackStates] = useState<Record<string, TrackState>>(
    {},
  );

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

  /**
   * Guards the board fetch so it happens once, not on every visit to the tab.
   *
   * A ref rather than the load state itself: the effect must not re-run when the state it sets
   * changes, or its cleanup would cancel the very request it just started. Cleared on failure, so
   * leaving the tab and coming back is the retry — and cleared again when a sweep finishes, since
   * a completed pass is the one thing that changes the posting set while the page is open.
   */
  const boardRequested = useRef(false);

  /**
   * Marks the board as needing a fresh read after a sweep has finished.
   *
   * Fetching immediately would load a list the user is not looking at, so the postings are simply
   * dropped and re-read the next time the tab is opened. Without this a user could run a sweep,
   * watch it report twelve new postings, switch to the board and see none of them until they
   * reloaded the page — a fetch that was only ever correct while nothing in the app could change
   * what had been swept.
   */
  const boardIsStale = useCallback(() => {
    boardRequested.current = false;
    setBoard({ kind: "idle" });
  }, []);

  useEffect(() => {
    if (tab !== "board" || boardRequested.current) return;
    boardRequested.current = true;
    setBoard({ kind: "loading" });

    listPostings()
      .then((postings) => setBoard({ kind: "ready", postings }))
      .catch((error: Error) => {
        boardRequested.current = false;
        setBoard({ kind: "error", message: error.message });
      });
  }, [tab]);

  const applications = load.kind === "ready" ? load.applications : [];
  const postings = board.kind === "ready" ? board.postings : [];

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

  /**
   * Chip counts for the board, each tallied against the other chip row rather than the whole
   * board, so a count says what clicking it would actually leave on screen.
   *
   * Neither honours the search box: a chip that shrank as you typed would stop being the fixed
   * landmark it is there to be.
   *
   * The region a posting belongs to is the one the API sends, so a chip counts exactly what the
   * table will show and the two can never disagree.
   */
  const regionCounts = useMemo(() => {
    const tally = Object.fromEntries(REGIONS.map((r) => [r, 0])) as Record<
      Region,
      number
    >;
    let anywhere = 0;

    for (const posting of postings) {
      if (postingStatus !== null && posting.status !== postingStatus) continue;
      anywhere += 1;
      tally[posting.region] += 1;
    }

    return { ...tally, anywhere };
  }, [postings, postingStatus]);

  const postingStatusCounts = useMemo(() => {
    const tally: Record<PostingStatus, number> = { open: 0, closed: 0 };
    for (const posting of postings) {
      if (region === null || posting.region === region) {
        tally[posting.status] += 1;
      }
    }
    return tally;
  }, [postings, region]);

  /** Headline numbers for the board tab, standing in for the application pipeline stats. */
  const boardTotals = useMemo(() => {
    let open = 0;
    let israel = 0;
    for (const posting of postings) {
      if (posting.status === "open") open += 1;
      if (posting.region === "israel") israel += 1;
    }
    return { open, israel };
  }, [postings]);

  const visiblePostings = useMemo(() => {
    const needle = boardQuery.trim().toLowerCase();
    const matched = postings.filter((posting) => {
      const matchesStatus =
        postingStatus === null || posting.status === postingStatus;
      const matchesQuery =
        needle === "" ||
        posting.company.toLowerCase().includes(needle) ||
        posting.title.toLowerCase().includes(needle) ||
        posting.location.toLowerCase().includes(needle);
      const matchesRegion = region === null || posting.region === region;
      return matchesStatus && matchesQuery && matchesRegion;
    });
    return sortPostings(matched, boardSort);
  }, [postings, postingStatus, boardQuery, region, boardSort]);

  /**
   * Posting links already sitting in the applications list.
   *
   * The url is the join between the two tabs — it is what the API enforces as unique, so it is
   * the only field where "the same job" means the same thing on both sides. Matching on company
   * and role instead would mark a second opening at the same company as already tracked.
   *
   * Built from the list already in state rather than by asking the API which postings are taken:
   * the answer is sitting here, and the board must not add a request to the tab it renders on.
   */
  const trackedUrls = useMemo(
    () =>
      new Set(
        applications
          .map((application) => application.url)
          .filter((url) => url !== ""),
      ),
    [applications],
  );

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

  /**
   * Destroys the application awaiting confirmation and drops it from the list.
   *
   * The row is removed only after the API confirms, unlike the optimistic status change. A status
   * that fails can be rolled back to its previous value; a row removed optimistically has nowhere
   * to roll back to except a refetch, and showing it briefly vanish and return reads as a bug.
   *
   * The removal is applied whatever the load state, so a delete that lands while the list is
   * reloading is not silently discarded.
   */
  async function confirmDelete() {
    if (pendingDelete.kind === "closed") return;
    const { application } = pendingDelete;
    setPendingDelete({ kind: "deleting", application });

    try {
      await deleteApplication(application.id);
      setLoad((current) =>
        current.kind === "ready"
          ? {
              ...current,
              applications: current.applications.filter(
                (candidate) => candidate.id !== application.id,
              ),
            }
          : current,
      );
      setRowStates((current) => {
        const { [application.id]: _removed, ...rest } = current;
        return rest;
      });
      setPendingDelete({ kind: "closed" });
    } catch (error) {
      setPendingDelete({
        kind: "failed",
        application,
        message: (error as Error).message,
      });
    }
  }

  /**
   * Copies a board posting into the applications list.
   *
   * The new application is `saved`, never `applied`. Pressing a button in this dashboard does not
   * send anything to anyone — the user still has to open the posting and actually apply — and the
   * applications tab already turns that into one click on the status pill when they have. Writing
   * `applied` here would invent history the tracker then reports back as fact.
   *
   * A 409 means the API already holds this url, which is precisely the state the click was asking
   * for; the loaded list simply did not know about it yet. It is recorded as tracked rather than
   * shown as a failure, and the list is left alone rather than refetched to prove the point.
   *
   * The row is only marked tracked once the write lands, unlike the optimistic status change on
   * the applications tab. There is nothing to roll back to here: a row that says Tracked and then
   * silently becomes a button again reads as the click having been lost.
   */
  async function trackPosting(posting: Posting) {
    setTrackStates((current) => ({
      ...current,
      [posting.id]: { kind: "saving" },
    }));

    try {
      const created = await createApplication({
        company: posting.company,
        role: posting.title,
        location: posting.location,
        url: posting.url,
        source: "Board tracker",
        status: "saved",
      });
      setLoad((current) =>
        current.kind === "ready"
          ? { ...current, applications: [created, ...current.applications] }
          : current,
      );
      setTrackStates((current) => ({
        ...current,
        [posting.id]: { kind: "tracked" },
      }));
    } catch (error) {
      const alreadyTracked = error instanceof ApiError && error.status === 409;
      setTrackStates((current) => ({
        ...current,
        [posting.id]: alreadyTracked
          ? { kind: "tracked" }
          : { kind: "failed", message: (error as Error).message },
      }));
    }
  }

  /** Clears a board row's error message, which otherwise stays pinned for the whole session. */
  function dismissTrackError(id: string) {
    setTrackStates((current) => ({ ...current, [id]: { kind: "idle" } }));
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
      <header className="flex items-end justify-between gap-6 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Logo />
            <h1 className="font-display text-lg font-extrabold tracking-tight">
              huntpilot
            </h1>
          </div>
          <p className="mt-1 text-xs text-ink-dim">
            {SUBTITLES[tab]}
          </p>
        </div>

        <div className="flex gap-7">
          {tab === "sweep" ? null : tab === "applications" ? (
            <>
              <Stat label="Tracked" value={applications.length} />
              <Stat label="Active" value={counts.applied + counts.interview} />
              <Stat label="Interviews" value={counts.interview} />
              <Stat label="Offers" value={counts.offer} />
            </>
          ) : (
            <>
              <Stat label="Swept" value={postings.length} />
              <Stat label="Open" value={boardTotals.open} />
              <Stat label="Israel" value={boardTotals.israel} />
            </>
          )}
        </div>
      </header>

      <Tabs value={tab} onChange={setTab} />

      {tab === "applications" ? (
        <>
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
              Could not reach the API — {load.message}. Is the backend running
              on port 8000?
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
              onDelete={(application) =>
                setPendingDelete({ kind: "confirming", application })
              }
              onAdd={() => setDialog({ kind: "open" })}
              emptyMessage={
                applications.length === 0
                  ? "Nothing tracked yet."
                  : "No applications match this filter."
              }
            />
          )}
        </>
      ) : tab === "board" ? (
        <>
          <BoardToolbar
            query={boardQuery}
            onQueryChange={setBoardQuery}
            region={region}
            onRegionChange={setRegion}
            regionCounts={regionCounts}
            status={postingStatus}
            onStatusChange={setPostingStatus}
            statusCounts={postingStatusCounts}
            shown={visiblePostings.length}
            total={postings.length}
          />

          {(board.kind === "idle" || board.kind === "loading") && (
            <Notice>Sweeping the board…</Notice>
          )}

          {board.kind === "error" && (
            <Notice tone="danger">
              Could not load the board — {board.message}. Switch tabs and back
              to try again.
            </Notice>
          )}

          {board.kind === "ready" && (
            <PostingsTable
              postings={visiblePostings}
              sort={boardSort}
              onSortChange={setBoardSort}
              trackedUrls={trackedUrls}
              trackStates={trackStates}
              onTrack={trackPosting}
              onDismissError={dismissTrackError}
              emptyMessage={
                postings.length === 0
                  ? "The sweep has not found any postings yet."
                  : "No postings match these filters."
              }
            />
          )}
        </>
      ) : (
        <SweepPanel onSwept={boardIsStale} />
      )}

      <AddApplicationDialog
        state={dialog}
        onClose={() => setDialog({ kind: "closed" })}
        onSubmit={add}
        onInvalid={(message) => setDialog({ kind: "invalid", message })}
      />

      <ConfirmDeleteDialog
        state={pendingDelete}
        onCancel={() => setPendingDelete({ kind: "closed" })}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

/**
 * The one-line description under the wordmark, per tab.
 *
 * A lookup rather than nested ternaries: with three tabs the conditional form stopped being
 * readable, and a missing entry is now a type error rather than a blank line.
 */
const SUBTITLES: Record<Tab, string> = {
  applications: "Every application, and what needs chasing.",
  board: "Every role the sweep found, and how long it has been open.",
  sweep: "Run a pass over the watchlist, and see what the last ones did.",
};

/**
 * The tab strip.
 *
 * Two buttons and a piece of state, not a router: the tabs are two views of one dashboard, and
 * nothing here is worth a URL, a dependency, or a page load.
 */
function Tabs({
  value,
  onChange,
}: {
  value: Tab;
  onChange: (tab: Tab) => void;
}) {
  const tabs: { id: Tab; label: string }[] = [
    { id: "applications", label: "Applications" },
    { id: "board", label: "Board" },
    { id: "sweep", label: "Sweep" },
  ];

  return (
    <nav className="flex gap-1 border-b border-line" aria-label="Views">
      {tabs.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          aria-current={value === id ? "page" : undefined}
          className={`-mb-px cursor-pointer border-b-2 px-3 pb-2.5 text-[13px] font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
            value === id
              ? "border-accent text-ink"
              : "border-transparent text-ink-dim hover:text-ink"
          }`}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}

/**
 * One headline number in the header.
 *
 * The number is monospaced and the label is small and quiet, so a row of them reads as a set of
 * figures at a glance rather than as a sentence to be parsed.
 */
/**
 * The radar mark, inline rather than an `<img>`.
 *
 * The sweep arc is the product: a board read, read again, and the difference reported. Inline so
 * it inherits `currentColor` for the rings and needs no second request for 700 bytes.
 */
function Logo() {
  return (
    <svg viewBox="0 0 64 64" className="h-[22px] w-[22px] text-ink" aria-hidden="true">
      <defs>
        <linearGradient
          id="sweep"
          x1="32"
          y1="32"
          x2="60"
          y2="12"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#5fa8d3" stopOpacity="0.85" />
          <stop offset="1" stopColor="#5fa8d3" stopOpacity="0" />
        </linearGradient>
      </defs>
      <circle
        cx="32"
        cy="32"
        r="27"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.28"
        strokeWidth="4"
      />
      <path d="M32 32 L32 5 A27 27 0 0 1 55.4 18.5 Z" fill="url(#sweep)" />
      <path
        d="M32 32 L55.4 18.5"
        stroke="#5fa8d3"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <circle cx="44" cy="24" r="5" fill="#5fa8d3" />
    </svg>
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

/**
 * A message standing where a table would be, while loading or after a failure.
 *
 * It occupies the same panel the rows would have filled, so the layout does not jump when the
 * data arrives and replaces it.
 */
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
        tone === "danger" ? "text-danger-ink" : "text-ink-dim"
      }`}
    >
      {children}
    </div>
  );
}
