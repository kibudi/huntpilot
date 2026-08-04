import { exactTime, relativeTime } from "../format";
import type { RowState } from "../state";
import { STATUSES, type Application, type Status } from "../types";
import { StatusSelect } from "./StatusSelect";

export type SortKey =
  | "company"
  | "role"
  | "location"
  | "source"
  | "status"
  | "applied_date"
  | "updated_at";

export interface Sort {
  key: SortKey;
  ascending: boolean;
}

const COLUMNS: { key: SortKey | null; label: string }[] = [
  { key: "company", label: "Company" },
  { key: "role", label: "Role" },
  { key: "location", label: "Location" },
  { key: "source", label: "Source" },
  { key: "status", label: "Status" },
  { key: "applied_date", label: "Applied" },
  { key: "updated_at", label: "Updated" },
  { key: null, label: "Notes" },
  { key: null, label: "" },
];

/** Columns that read most usefully newest-first when first selected. */
const DESCENDING_FIRST: SortKey[] = ["status", "applied_date", "updated_at"];

/** Returns the value a row is ordered by, with status mapped to its pipeline position. */
function sortValue(application: Application, key: SortKey): string | number {
  if (key === "status") return STATUSES.indexOf(application.status);
  return application[key] ?? "";
}

/**
 * Orders applications by the active sort.
 *
 * Rows missing the sort value always sink to the bottom regardless of direction: an unapplied job
 * has no date, and that is absence of data rather than an early one.
 */
export function sortApplications(
  applications: Application[],
  sort: Sort,
): Application[] {
  const direction = sort.ascending ? 1 : -1;

  return [...applications].sort((left, right) => {
    const a = sortValue(left, sort.key);
    const b = sortValue(right, sort.key);

    if (a === "" && b === "") return 0;
    if (a === "") return 1;
    if (b === "") return -1;
    if (typeof a === "number" && typeof b === "number") {
      return (a - b) * direction;
    }
    return String(a).localeCompare(String(b)) * direction;
  });
}

/** The default direction when a column is first selected. */
export function defaultAscending(key: SortKey): boolean {
  return !DESCENDING_FIRST.includes(key);
}

export function ApplicationsTable({
  applications,
  sort,
  onSortChange,
  rowStates,
  onStatusChange,
  onDismissError,
  onDelete,
  emptyMessage,
  onAdd,
}: {
  applications: Application[];
  sort: Sort;
  onSortChange: (sort: Sort) => void;
  rowStates: Record<string, RowState>;
  onStatusChange: (application: Application, next: Status) => void;
  onDismissError: (id: string) => void;
  onDelete: (application: Application) => void;
  emptyMessage: string;
  onAdd: () => void;
}) {
  function toggle(key: SortKey) {
    onSortChange(
      key === sort.key
        ? { key, ascending: !sort.ascending }
        : { key, ascending: defaultAscending(key) },
    );
  }

  return (
    <div className="overflow-auto rounded-lg border border-line bg-panel">
      <table className="w-full min-w-[1180px] border-collapse text-left">
        <thead className="sticky top-0 z-10 bg-panel">
          <tr>
            {COLUMNS.map(({ key, label }) => (
              <th
                key={label}
                scope="col"
                aria-sort={
                  key === sort.key
                    ? sort.ascending
                      ? "ascending"
                      : "descending"
                    : undefined
                }
                className="border-b border-line px-3.5 py-2.5 text-[11px] font-semibold tracking-[0.04em] text-ink-dim uppercase"
              >
                {key ? (
                  <button
                    type="button"
                    onClick={() => toggle(key)}
                    className="cursor-pointer tracking-[0.04em] uppercase hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  >
                    {label}
                    {key === sort.key && (
                      <span className="ml-1 text-accent">
                        {sort.ascending ? "▲" : "▼"}
                      </span>
                    )}
                  </button>
                ) : (
                  label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {applications.length === 0 ? (
            <tr>
              <td colSpan={COLUMNS.length} className="px-3.5 py-16 text-center">
                <p className="text-ink-dim">{emptyMessage}</p>
                <button
                  type="button"
                  onClick={onAdd}
                  className="mt-3 rounded-[7px] bg-accent px-3.5 py-2 text-[13px] font-semibold text-page hover:bg-accent-bright"
                >
                  Add your first application
                </button>
              </td>
            </tr>
          ) : (
            applications.map((application) => (
              <Row
                key={application.id}
                application={application}
                state={rowStates[application.id] ?? { kind: "idle" }}
                onStatusChange={onStatusChange}
                onDismissError={() => onDismissError(application.id)}
                onDelete={() => onDelete(application)}
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function Row({
  application,
  state,
  onStatusChange,
  onDismissError,
  onDelete,
}: {
  application: Application;
  state: RowState;
  onStatusChange: (application: Application, next: Status) => void;
  onDismissError: () => void;
  onDelete: () => void;
}) {
  return (
    <tr className="group border-t border-line hover:bg-raised">
      <td className="px-3.5 py-2.5">
        {application.url ? (
          <a
            href={application.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-ink hover:text-accent"
          >
            {application.company}
          </a>
        ) : (
          <span className="font-semibold text-ink" title="No posting link recorded">
            {application.company}
          </span>
        )}
        {state.kind === "failed" && (
          <button
            type="button"
            onClick={onDismissError}
            title="Dismiss"
            className="ml-2 text-xs text-danger hover:underline"
          >
            {state.message} ✕
          </button>
        )}
      </td>
      <td className="px-3.5 py-2.5">{application.role}</td>
      <td className="px-3.5 py-2.5 text-ink-dim">{application.location}</td>
      <td className="px-3.5 py-2.5 text-ink-dim">{application.source}</td>
      <td className="px-3.5 py-2.5">
        <StatusSelect
          value={application.status}
          disabled={state.kind === "saving"}
          onChange={(next) => onStatusChange(application, next)}
        />
      </td>
      <td className="px-3.5 py-2.5 font-mono text-xs text-ink-dim">
        {application.applied_date ?? "—"}
      </td>
      <td
        className="px-3.5 py-2.5 font-mono text-xs text-ink-dim"
        title={exactTime(application.updated_at)}
      >
        {relativeTime(application.updated_at)}
      </td>
      <td className="px-3.5 py-2.5 text-ink-dim">
        <div
          className="max-w-[220px] truncate"
          title={application.notes || undefined}
        >
          {application.notes || "—"}
        </div>
      </td>
      <td className="px-3.5 py-2.5 text-right">
        <button
          type="button"
          onClick={onDelete}
          disabled={state.kind === "saving"}
          title={`Delete ${application.company} — ${application.role}`}
          aria-label={`Delete ${application.company} — ${application.role}`}
          className="cursor-pointer rounded px-1.5 text-ink-dim opacity-0 group-hover:opacity-100 hover:text-danger focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-0"
        >
          ✕
        </button>
      </td>
    </tr>
  );
}
