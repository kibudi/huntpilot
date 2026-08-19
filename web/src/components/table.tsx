/**
 * The parts the applications table and the board table share: ordering rows by a column, and the
 * header row that chooses which column that is.
 *
 * Both tables are the same object — a sortable grid of records — over different records, so the
 * sorting and the header were written twice and then had to be kept in step by hand. Everything
 * that differs between them is data: which columns exist, and what value a row contributes for a
 * given column. That is what the two tables still own; the mechanics live here once.
 */

/** The active sort: which column rows are ordered by, and which way. */
export interface SortState<K extends string> {
  key: K;
  ascending: boolean;
}

/**
 * One column heading.
 *
 * `key` is `null` for a column that cannot be sorted — a notes cell or a row of buttons — and
 * those headings render as plain text rather than a dead button.
 */
export interface Column<K extends string> {
  key: K | null;
  label: string;
  /**
   * Whether the column starts descending the first time it is picked.
   *
   * Dates and counts read most usefully largest-first: the newest application and the role that
   * has been open longest are what the column is being clicked for. Names read A to Z.
   */
  descendingFirst?: boolean;
}

/**
 * Orders rows by the active sort, given the value each row contributes for a column.
 *
 * Rows missing that value always sink to the bottom regardless of direction: an unapplied job has
 * no date and a posting can carry no location at all, and that is absence of data rather than an
 * early one.
 *
 * Sorts a copy. The caller's array is the list held in state, and reordering it in place would
 * mutate state React was told is immutable.
 */
export function sortRows<T, K extends string>(
  rows: T[],
  sort: SortState<K>,
  valueOf: (row: T, key: K) => string | number,
): T[] {
  const direction = sort.ascending ? 1 : -1;

  return [...rows].sort((left, right) => {
    const a = valueOf(left, sort.key);
    const b = valueOf(right, sort.key);

    if (a === "" && b === "") return 0;
    if (a === "") return 1;
    if (b === "") return -1;
    if (typeof a === "number" && typeof b === "number") {
      return (a - b) * direction;
    }
    return String(a).localeCompare(String(b)) * direction;
  });
}

/** The direction a column takes when it is first selected. */
export function defaultAscending<K extends string>(column: Column<K>): boolean {
  return !column.descendingFirst;
}

/**
 * The header row: one heading per column, sortable ones as buttons.
 *
 * Clicking the column already sorted flips its direction; clicking any other switches to it in
 * whichever direction that column reads best. `aria-sort` carries the same fact the arrow does,
 * so the ordering is not something only a sighted user is told.
 */
export function SortableHeader<K extends string>({
  columns,
  sort,
  onSortChange,
}: {
  columns: Column<K>[];
  sort: SortState<K>;
  onSortChange: (sort: SortState<K>) => void;
}) {
  function toggle(column: Column<K>, key: K) {
    onSortChange(
      key === sort.key
        ? { key, ascending: !sort.ascending }
        : { key, ascending: defaultAscending(column) },
    );
  }

  return (
    <thead className="sticky top-0 z-10 bg-panel">
      <tr>
        {columns.map((column) => {
          const { key, label } = column;
          return (
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
                  onClick={() => toggle(column, key)}
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
          );
        })}
      </tr>
    </thead>
  );
}
