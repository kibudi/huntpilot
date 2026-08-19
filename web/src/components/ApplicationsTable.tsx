import { exactTime, relativeTime } from "../format";
import type { RowState } from "../state";
import { STATUSES, type Application, type Status } from "../types";
import { StatusSelect } from "./StatusSelect";
import { SortableHeader, sortRows, type Column } from "./table";

/** The columns an application can be ordered by. */
export type SortKey =
  | "company"
  | "role"
  | "location"
  | "source"
  | "status"
  | "applied_date"
  | "updated_at";

/** Which column the applications are ordered by, and which way. */
export interface Sort {
  key: SortKey;
  ascending: boolean;
}

/** The headings, in the order they are shown. The last two sort nothing. */
const COLUMNS: Column<SortKey>[] = [
  { key: "company", label: "Company" },
  { key: "role", label: "Role" },
  { key: "location", label: "Location" },
  { key: "source", label: "Source" },
  { key: "status", label: "Status", descendingFirst: true },
  { key: "applied_date", label: "Applied", descendingFirst: true },
  { key: "updated_at", label: "Updated", descendingFirst: true },
  { key: null, label: "Notes" },
  { key: null, label: "" },
];

/** Returns the value a row is ordered by, with status mapped to its pipeline position. */
function sortValue(application: Application, key: SortKey): string | number {
  if (key === "status") return STATUSES.indexOf(application.status);
  return application[key] ?? "";
}

/** Orders applications by the active sort. */
export function sortApplications(
  applications: Application[],
  sort: Sort,
): Application[] {
  return sortRows(applications, sort, sortValue);
}

/**
 * The pipeline: every tracked application, one row each.
 *
 * The status pill and the delete button live in the row itself rather than behind a menu, because
 * moving a job along is the thing this screen exists to do and it should cost one click.
 */
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
  return (
    <div className="overflow-auto rounded-lg border border-line bg-panel">
      <table className="w-full min-w-[1180px] border-collapse text-left">
        <SortableHeader
          columns={COLUMNS}
          sort={sort}
          onSortChange={onSortChange}
        />
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

/**
 * One application.
 *
 * The company name is the posting link where there is one, and plain text where there is not —
 * an application can be logged without a url, and a link to nowhere is worse than no link.
 */
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
