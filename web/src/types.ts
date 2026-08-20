/** The application record as the API returns it. Field names match the backend exactly. */
export interface Application {
  id: string;
  company: string;
  role: string;
  location: string;
  source: string;
  url: string;
  status: Status;
  /** `YYYY-MM-DD`, or null while the job has only been saved. */
  applied_date: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export type Status =
  | "saved"
  | "applied"
  | "interview"
  | "offer"
  | "rejected"
  | "ghosted";

/**
 * Statuses in pipeline order.
 *
 * The index doubles as the sort key, so the Status column orders by stage rather than
 * alphabetically — the ordering a pipeline is actually read in.
 */
export const STATUSES: Status[] = [
  "saved",
  "applied",
  "interview",
  "offer",
  "rejected",
  "ghosted",
];

/**
 * Chroma and hue per status, used to build both the pill background and its text colour.
 *
 * Deriving both from one pattern keeps the six pills visually consistent; picking each colour by
 * hand does not.
 */
export const STATUS_COLOR: Record<Status, { c: number; h: number }> = {
  saved: { c: 0.03, h: 70 },
  applied: { c: 0.07, h: 210 },
  interview: { c: 0.1, h: 195 },
  offer: { c: 0.12, h: 165 },
  rejected: { c: 0.1, h: 35 },
  ghosted: { c: 0, h: 0 },
};

/**
 * A job posting the board tracker swept from a company's job board, as the API returns it.
 *
 * Field names match the backend exactly. Nothing here is editable: the sweep owns every value,
 * and the dashboard only reads them.
 */
export interface Posting {
  id: string;
  company: string;
  ats: Ats;
  title: string;
  location: string;
  url: string;
  status: PostingStatus;
  region: Region;
  /** ISO timestamp of the sweep that first saw the posting. */
  first_seen_at: string;
  /** ISO timestamp of the most recent sweep that still saw it. */
  last_seen_at: string;
  /** ISO timestamp of the sweep that found it gone, or null while it is still listed. */
  closed_at: string | null;
}

/** The board software a posting was swept from. */
export type Ats = "greenhouse" | "lever" | "ashby";

/**
 * Where a posting places the job, as the storage layer decided it.
 *
 * The sweep stores `location` as raw text straight off each board, and the boards do not agree
 * with each other: the same city arrives as "Tel Aviv", "Tel Aviv District, Israel", "Tel
 * Aviv-Yafo, Gush Dan, Israel" and "TLV". Reading that text is the backend's job — it is the side
 * that already has to decide, because a posting only gets stored if it lands somewhere worth
 * looking at. The dashboard reads the verdict and never re-derives it: a second copy of the rule
 * here would drift from the first, and the chips would quietly undercount the places the copy had
 * not heard of.
 */
export type Region = "israel" | "remote";

/** `null` means no region narrowing — every posting the sweep stored. */
export type RegionFilter = Region | null;

/** Regions offered as chips, in the order they appear. */
export const REGIONS: Region[] = ["israel", "remote"];

/**
 * Whether a posting is still listed on the company's board.
 *
 * A posting is never deleted when it disappears — it is closed and kept, because how long a role
 * stayed open is part of what the board tab is for.
 */
export type PostingStatus = "open" | "closed";

/** Fields a client may supply when creating an application. */
export interface ApplicationCreate {
  company: string;
  role: string;
  location: string;
  source: string;
  url: string;
  status?: Status;
  applied_date?: string | null;
  notes?: string;
}

/**
 * One recorded pass over the watchlist, as the API returns it.
 *
 * Field names match the backend exactly. Nothing here is editable: a run is a record of something
 * that happened, and the dashboard's only writes are starting one.
 */
export interface SweepRun {
  id: string;
  state: SweepState;
  /** ISO timestamp of the moment the run was recorded, before the first board was read. */
  started_at: string;
  /** ISO timestamp of the moment it reached a final state, or null while it is still going. */
  finished_at: string | null;
  /** Null until the pass is over — a sweep on its first board and one that stored nothing differ. */
  summary: SweepSummary | null;
  /** Why the sweep as a whole failed, which is not the same as a board failing. */
  error: string | null;
}

/**
 * Where one recorded sweep got to.
 *
 * `completed` covers a pass in which individual boards failed: that is contained by design and
 * already counted in the summary, so it is not a separate outcome.
 */
export type SweepState = "running" | "completed" | "failed" | "abandoned";

/**
 * What one pass did, as the API returns it.
 *
 * The posting counts are totals across the boards that were actually read, which is why
 * `boards_failed` is shown beside them and never on its own: a sweep where half the boards failed
 * produces small, honest-looking counts, and only the failure count says the sweep saw half the
 * market.
 */
export interface SweepSummary {
  boards_swept: number;
  boards_failed: number;
  added: number;
  still_open: number;
  closed: number;
  reopened: number;
  failures: BoardFailure[];
}

/** One board that could not be read during a sweep, and why. */
export interface BoardFailure {
  name: string;
  ats: Ats;
  token: string;
  error: string;
}

/**
 * The search every sweep is run against, as the API returns it and accepts it back.
 *
 * One interface for both directions because the API publishes one shape for both, which is what
 * makes the editor work: it is filled from a `GET` and posted back to a `PUT`, so a field present
 * in one direction and absent in the other would be a trap.
 *
 * Patterns are strings, exactly as they are written in the profile file. They are compiled by the
 * API, never here — the browser does not filter anything and has no use for a compiled pattern.
 */
export interface Profile {
  /** City and district spellings that count as local. Matched against lower-cased text. */
  local_fragments: string[];
  /** Wordings that count as advertised remote. */
  remote_fragments: string[];
  /** One pattern whose match in a title rules the posting out as too senior. */
  seniority_markers: string;
  /** Role family name to the pattern that recognises it, tried in the order given. */
  role_families: Record<string, string>;
  /** Technology name to the pattern that recognises it, for technologies already known. */
  known: Record<string, string>;
  /** The same, for technologies counted against a posting rather than for it. */
  unknown: Record<string, string>;
  /** Share of a posting's named technologies that must be known, as a fraction of one. */
  min_tech_score: number;
  /** The most years of experience a posting may ask for and still be kept. */
  max_years: number;
}
