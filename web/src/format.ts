/**
 * Renders an ISO timestamp as a short relative time, e.g. "3d ago".
 *
 * The table is scanned for what needs chasing, and "5d ago" answers that faster than a date does.
 * The exact timestamp stays available as a tooltip.
 */
export function relativeTime(iso: string): string {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "unknown";

  const seconds = (Date.now() - time) / 1000;
  if (seconds < 0) return "in the future";

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`;
  if (seconds < 31536000) return `${Math.floor(seconds / 2592000)}mo ago`;
  return `${Math.floor(seconds / 31536000)}y ago`;
}

/** Renders an ISO timestamp in full, for the tooltip behind the relative time. */
export function exactTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unrecognised timestamp";

  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Today as `YYYY-MM-DD` in the viewer's own timezone.
 *
 * Built from the local date parts rather than `toISOString`, which converts to UTC first: at
 * 01:30 in UTC+3 that would stamp yesterday's date.
 */
export function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}
