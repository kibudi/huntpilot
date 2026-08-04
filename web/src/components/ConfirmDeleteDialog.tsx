import { useEffect, useRef } from "react";
import type { DeleteState } from "../state";

/**
 * Confirms destroying one application.
 *
 * The company and role are named in the body rather than the dialog saying "this application",
 * because the button that opened it sits in a dense table where the pointer is one row away from
 * a different job. Naming the target is what makes a misclick recoverable, since the deletion
 * itself is not — there is no undo and the API keeps no copy.
 *
 * Focus lands on Cancel, not Delete, so an Enter keypress arriving from the table underneath
 * dismisses the dialog instead of confirming it.
 */
export function ConfirmDeleteDialog({
  state,
  onCancel,
  onConfirm,
}: {
  state: DeleteState;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelButton = useRef<HTMLButtonElement>(null);
  const open = state.kind !== "closed";
  const busy = state.kind === "deleting";

  const latest = useRef({ onCancel, busy });
  latest.current = { onCancel, busy };

  useEffect(() => {
    if (!open) return;

    cancelButton.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !latest.current.busy) {
        latest.current.onCancel();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (state.kind === "closed") return null;

  const { company, role } = state.application;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "oklch(10% 0.01 250 / 65%)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-application-heading"
        className="w-[420px] rounded-[10px] border border-line bg-panel p-5"
      >
        <h2
          id="delete-application-heading"
          className="font-display text-base font-bold"
        >
          Delete application?
        </h2>

        <p className="mt-3 text-[13px] text-ink">
          <span className="font-semibold">{company}</span>
          <span className="text-ink-dim"> — {role}</span>
        </p>
        <p className="mt-1.5 text-xs text-ink-dim">
          This cannot be undone.
        </p>

        {state.kind === "failed" && (
          <p className="mt-3 text-xs text-danger" role="alert">
            {state.message}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelButton}
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-[7px] border border-line px-3.5 py-2 text-[13px] font-semibold text-ink-dim hover:border-line-strong hover:text-ink disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-[7px] bg-danger px-3.5 py-2 text-[13px] font-semibold text-page hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
