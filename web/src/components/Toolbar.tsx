import { STATUSES, type Status } from "../types";

/** `null` means no status filter is applied. */
export type StatusFilter = Status | null;

/** Search field, status filter chips, and the add button. */
export function Toolbar({
  query,
  onQueryChange,
  filter,
  onFilterChange,
  counts,
  total,
  onAdd,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  filter: StatusFilter;
  onFilterChange: (value: StatusFilter) => void;
  counts: Record<Status, number>;
  total: number;
  onAdd: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 py-4">
      <SearchField
        value={query}
        onChange={onQueryChange}
        label="Search company or role"
      />

      <Chip
        label="All"
        count={total}
        active={filter === null}
        onClick={() => onFilterChange(null)}
      />
      {STATUSES.map((status) => (
        <Chip
          key={status}
          label={status}
          count={counts[status]}
          active={filter === status}
          onClick={() => onFilterChange(filter === status ? null : status)}
        />
      ))}

      <button
        type="button"
        onClick={onAdd}
        className="ml-auto flex items-center gap-1.5 rounded-[7px] bg-accent px-3.5 py-2 text-[13px] font-semibold text-page transition-colors hover:bg-accent-bright"
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
        Add application
      </button>
    </div>
  );
}

/**
 * A magnifier-prefixed text field.
 *
 * Shared with the board toolbar, which needs two of them side by side. The label doubles as the
 * placeholder so the field explains itself without a heading taking up a line above it.
 */
export function SearchField({
  value,
  onChange,
  label,
  icon,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  icon?: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 rounded-[7px] border border-line bg-panel px-2.5 py-1.5 focus-within:border-line-strong">
      {icon ?? (
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="shrink-0 text-ink-faint"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" strokeLinecap="round" />
        </svg>
      )}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={label}
        aria-label={label}
        className="w-52 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-faint"
      />
    </label>
  );
}

/** One filter chip, showing a live count of matching rows. */
export function Chip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-2.5 py-1.5 text-xs font-semibold capitalize transition-colors ${
        active
          ? "bg-accent text-page"
          : "border border-line text-ink-dim hover:border-line-strong hover:text-ink"
      }`}
    >
      {label}
      <span className={active ? "ml-1.5 opacity-70" : "ml-1.5 text-ink-faint"}>
        {count}
      </span>
    </button>
  );
}
