import { STATUS_COLOR, STATUSES, type Status } from "../types";

/**
 * The status cell: a native select styled as a coloured pill.
 *
 * This is the primary daily action, so it is an inline control rather than something behind a
 * row menu. Every status is always offered regardless of the current one, so any transition —
 * including correcting a mistake backwards — is a single click.
 */
export function StatusSelect({
  value,
  onChange,
  disabled,
}: {
  value: Status;
  onChange: (next: Status) => void;
  disabled?: boolean;
}) {
  const { c, h } = STATUS_COLOR[value];

  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as Status)}
      aria-label="Status"
      className="cursor-pointer appearance-none rounded-full py-1 pr-2 pl-2.5 text-xs font-semibold capitalize outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
      style={{
        background: `oklch(91% ${c * 0.6} ${h})`,
        color: `oklch(38% ${Math.max(c, 0.01)} ${h})`,
      }}
    >
      {STATUSES.map((status) => (
        <option key={status} value={status} className="bg-panel text-ink">
          {status}
        </option>
      ))}
    </select>
  );
}
