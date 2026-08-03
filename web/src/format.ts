/**
 * Renders an ISO timestamp as a short relative time, e.g. "3d ago".
 *
 * The table is scanned for what needs chasing, and "5d ago" answers that faster than a date does.
 * The exact timestamp stays available as a tooltip.
 */
export function relativeTime(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`;
  if (seconds < 31536000) return `${Math.floor(seconds / 2592000)}mo ago`;
  return `${Math.floor(seconds / 31536000)}y ago`;
}

/** Renders an ISO timestamp in full, for the tooltip behind the relative time. */
export function exactTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Today as `YYYY-MM-DD`, for stamping an applied date locally. */
export function today(): string {
  return new Date().toISOString().slice(0, 10);
}
