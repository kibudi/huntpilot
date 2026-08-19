import {
  REGIONS,
  type PostingStatus,
  type Region,
  type RegionFilter,
} from "../types";
import { Chip, SearchField } from "./Toolbar";

/** `null` shows open and closed postings together. */
export type PostingStatusFilter = PostingStatus | null;

/**
 * Search field, region chips, open/closed chips, and how much of the board is showing.
 *
 * Built from the same `SearchField` and `Chip` the applications toolbar uses, so the two tabs
 * read as one screen, but the controls themselves are different: the applications toolbar finds
 * one known row in a list the user wrote, and this one cuts an already-filtered set — every
 * posting stored is somewhere worth working — into the parts worth reading in one sitting.
 *
 * Region comes before status because it is the cut that changes what the tab is for: Israel is
 * the job the user can take today, and remote is the one that still has to be argued for.
 */
export function BoardToolbar({
  query,
  onQueryChange,
  region,
  onRegionChange,
  regionCounts,
  status,
  onStatusChange,
  statusCounts,
  shown,
  total,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  region: RegionFilter;
  onRegionChange: (value: RegionFilter) => void;
  /**
   * One count per region, plus `anywhere`: the postings left by the status chips alone, which is
   * what clearing the region would show.
   */
  regionCounts: Record<Region, number> & { anywhere: number };
  status: PostingStatusFilter;
  onStatusChange: (value: PostingStatusFilter) => void;
  statusCounts: Record<PostingStatus, number>;
  shown: number;
  total: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 py-4">
      <SearchField
        value={query}
        onChange={onQueryChange}
        label="Search company, title or location"
      />

      <Chip
        label="Anywhere"
        count={regionCounts.anywhere}
        active={region === null}
        onClick={() => onRegionChange(null)}
      />
      {REGIONS.map((candidate) => (
        <Chip
          key={candidate}
          label={candidate}
          count={regionCounts[candidate]}
          active={region === candidate}
          onClick={() =>
            onRegionChange(region === candidate ? null : candidate)
          }
        />
      ))}

      <span className="mx-1 h-5 w-px bg-line" aria-hidden="true" />

      <Chip
        label="Open"
        count={statusCounts.open}
        active={status === "open"}
        onClick={() => onStatusChange("open")}
      />
      <Chip
        label="Closed"
        count={statusCounts.closed}
        active={status === "closed"}
        onClick={() => onStatusChange("closed")}
      />
      <Chip
        label="Both"
        count={statusCounts.open + statusCounts.closed}
        active={status === null}
        onClick={() => onStatusChange(null)}
      />

      <p className="ml-auto text-xs text-ink-dim">
        Showing{" "}
        <span className="font-mono text-ink">{shown.toLocaleString()}</span> of{" "}
        <span className="font-mono">{total.toLocaleString()}</span> swept
      </p>
    </div>
  );
}
