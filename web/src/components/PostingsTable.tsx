import { exactTime, relativeTime } from "../format";
import type { TrackState } from "../state";
import type { Posting } from "../types";
import { SortableHeader, sortRows, type Column } from "./table";

/** The columns a posting can be ordered by. `days` is derived rather than stored. */
export type PostingSortKey =
  | "company"
  | "title"
  | "location"
  | "days"
  | "first_seen_at";

/** Which column the postings are ordered by, and which way. */
export interface PostingSort {
  key: PostingSortKey;
  ascending: boolean;
}

/** The headings, in the order they are shown. The last holds the row's actions. */
const COLUMNS: Column<PostingSortKey>[] = [
  { key: "company", label: "Company" },
  { key: "title", label: "Title" },
  { key: "location", label: "Location" },
  { key: "days", label: "Days listed", descendingFirst: true },
  { key: "first_seen_at", label: "First seen", descendingFirst: true },
  { key: null, label: "" },
];

/**
 * How many whole days a posting has been listed.
 *
 * Measured from the first sweep that saw it to the sweep that found it gone, or to now while it
 * is still open. Stopping the clock at `closed_at` matters: a role that ran twelve days and shut
 * last spring should keep saying twelve, not grow forever alongside the ones still live.
 *
 * The number is the point of the column. A date says when a role appeared; "80" says the company
 * has been unable or unwilling to fill it for eighty days, which is the part worth reacting to.
 */
function daysListed(posting: Posting): number {
  const start = new Date(posting.first_seen_at).getTime();
  if (Number.isNaN(start)) return 0;

  const closed = posting.closed_at ? new Date(posting.closed_at).getTime() : NaN;
  const end = Number.isNaN(closed) ? Date.now() : closed;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

/** Returns the value a row is ordered by, with the derived days column computed on the fly. */
function sortValue(posting: Posting, key: PostingSortKey): string | number {
  if (key === "days") return daysListed(posting);
  return posting[key];
}

/** Orders postings by the active sort. */
export function sortPostings(
  postings: Posting[],
  sort: PostingSort,
): Posting[] {
  return sortRows(postings, sort, sortValue);
}

/**
 * The board: every posting the sweep kept, one row each.
 *
 * A posting is something the sweep observed, so there is nothing here to edit or delete. The two
 * actions are opening the ad and tracking it — the second is the only door between the board and
 * the applications the user is actually chasing.
 */
export function PostingsTable({
  postings,
  sort,
  onSortChange,
  trackedUrls,
  trackStates,
  onTrack,
  onDismissError,
  emptyMessage,
}: {
  postings: Posting[];
  sort: PostingSort;
  onSortChange: (sort: PostingSort) => void;
  trackedUrls: Set<string>;
  trackStates: Record<string, TrackState>;
  onTrack: (posting: Posting) => void;
  onDismissError: (id: string) => void;
  emptyMessage: string;
}) {
  return (
    <div className="overflow-auto rounded-lg border border-line bg-panel">
      <table className="w-full min-w-[1000px] border-collapse text-left">
        <SortableHeader
          columns={COLUMNS}
          sort={sort}
          onSortChange={onSortChange}
        />
        <tbody>
          {postings.length === 0 ? (
            <tr>
              <td colSpan={COLUMNS.length} className="px-3.5 py-16 text-center">
                <p className="text-ink-dim">{emptyMessage}</p>
              </td>
            </tr>
          ) : (
            postings.map((posting) => {
              const state = trackStates[posting.id] ?? { kind: "idle" };
              return (
                <Row
                  key={posting.id}
                  posting={posting}
                  state={state}
                  tracked={
                    state.kind === "tracked" || trackedUrls.has(posting.url)
                  }
                  onTrack={() => onTrack(posting)}
                  onDismissError={() => onDismissError(posting.id)}
                />
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One posting.
 *
 * A closed posting is dimmed rather than hidden or dropped, and says when it closed. It is still
 * evidence — of a company that hires for this role, and of how fast that window shut — but it is
 * not something to act on today, and the row should read that way at a glance.
 */
function Row({
  posting,
  state,
  tracked,
  onTrack,
  onDismissError,
}: {
  posting: Posting;
  state: TrackState;
  tracked: boolean;
  onTrack: () => void;
  onDismissError: () => void;
}) {
  const closed = posting.status === "closed";
  const days = daysListed(posting);

  return (
    <tr
      className={`border-t border-line hover:bg-raised ${
        closed ? "text-ink-faint" : ""
      }`}
    >
      <td className="px-3.5 py-2.5">
        <span className={closed ? "font-semibold" : "font-semibold text-ink"}>
          {posting.company}
        </span>
        {state.kind === "failed" && (
          <button
            type="button"
            onClick={onDismissError}
            title="Dismiss"
            className="ml-2 text-xs text-danger-ink hover:underline"
          >
            {state.message} ✕
          </button>
        )}
        {closed && posting.closed_at && (
          <span
            title={`Closed ${exactTime(posting.closed_at)}`}
            className="ml-2 rounded-full border border-line px-1.5 py-0.5 text-[11px] whitespace-nowrap"
          >
            closed {relativeTime(posting.closed_at)}
          </span>
        )}
      </td>
      <td className="px-3.5 py-2.5">{posting.title}</td>
      <td className={`px-3.5 py-2.5 ${closed ? "" : "text-ink-dim"}`}>
        {posting.location || "—"}
      </td>
      <td
        className="px-3.5 py-2.5 font-mono text-xs"
        title={
          closed
            ? `Listed for ${days} days before it closed`
            : `Open for ${days} days`
        }
      >
        {days}d
      </td>
      <td
        className={`px-3.5 py-2.5 font-mono text-xs ${closed ? "" : "text-ink-dim"}`}
        title={exactTime(posting.first_seen_at)}
      >
        {relativeTime(posting.first_seen_at)}
      </td>
      <td className="px-3.5 py-2.5">
        <div className="flex items-center justify-end gap-3">
          <TrackButton
            posting={posting}
            state={state}
            tracked={tracked}
            onTrack={onTrack}
          />
          <a
            href={posting.url}
            target="_blank"
            rel="noopener noreferrer"
            title={`Open on ${posting.ats}`}
            className="text-ink-dim hover:text-accent"
          >
            Open ↗
          </a>
        </div>
      </td>
    </tr>
  );
}

/**
 * Copies one posting into the applications list.
 *
 * A posting already in the pipeline shows as plain text rather than a disabled button: the point
 * of the label is telling the user at a glance which rows they have already picked up, and a
 * button they cannot press invites clicking to find out why.
 */
function TrackButton({
  posting,
  state,
  tracked,
  onTrack,
}: {
  posting: Posting;
  state: TrackState;
  tracked: boolean;
  onTrack: () => void;
}) {
  if (tracked) {
    return (
      <span
        title="Already on the Applications tab"
        className="px-2 py-1 text-xs font-semibold text-ink-faint"
      >
        ✓ Tracked
      </span>
    );
  }

  const saving = state.kind === "saving";

  return (
    <button
      type="button"
      onClick={onTrack}
      disabled={saving}
      title={`Track ${posting.company} — ${posting.title} as an application`}
      className="cursor-pointer rounded-[7px] border border-line px-2 py-1 text-xs font-semibold text-ink-dim transition-colors hover:border-line-strong hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:cursor-default disabled:opacity-50"
    >
      {saving ? "Tracking…" : "Track"}
    </button>
  );
}
