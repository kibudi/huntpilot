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
  saved: { c: 0.02, h: 240 },
  applied: { c: 0.16, h: 250 },
  interview: { c: 0.15, h: 300 },
  offer: { c: 0.16, h: 145 },
  rejected: { c: 0.09, h: 25 },
  ghosted: { c: 0, h: 0 },
};

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
