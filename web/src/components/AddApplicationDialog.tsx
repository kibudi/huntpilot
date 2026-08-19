import { useEffect, useRef, useState } from "react";
import type { DialogState } from "../state";
import { STATUSES, type ApplicationCreate, type Status } from "../types";

/**
 * An empty form.
 *
 * Every field is a string, including the date and the status, because that is what an `<input>`
 * hands back. The conversion to what the API wants happens once, on submit.
 */
const BLANK = {
  company: "",
  role: "",
  location: "",
  source: "",
  url: "",
  status: "saved" as Status,
  applied_date: "",
  notes: "",
};

/**
 * Required fields, with the labels the form shows, so a validation message names what the user
 * sees.
 *
 * The posting URL is deliberately absent. Plenty of real applications start from a referral, a
 * recruiter message or an ad that has since been taken down, and there is no link to paste; the
 * API stores those with an empty url, which is why its uniqueness rule only covers rows that have
 * one. Demanding a link here would make this form the one path that cannot record them.
 */
const REQUIRED: { field: keyof typeof BLANK; label: string }[] = [
  { field: "company", label: "Company" },
  { field: "role", label: "Role" },
  { field: "location", label: "Location" },
  { field: "source", label: "Source" },
];

/**
 * The add-application dialog.
 *
 * Required fields are checked here before submitting, so an obvious omission does not cost a
 * round trip. The API validates independently — this is a convenience, not the guarantee.
 */
export function AddApplicationDialog({
  state,
  onClose,
  onSubmit,
  onInvalid,
}: {
  state: DialogState;
  onClose: () => void;
  onSubmit: (payload: ApplicationCreate) => void;
  onInvalid: (message: string) => void;
}) {
  const [fields, setFields] = useState(BLANK);
  const firstField = useRef<HTMLInputElement>(null);
  const open = state.kind !== "closed";

  /**
   * Clears the form whenever the dialog closes.
   *
   * The component is never unmounted — it returns null while closed — so its state survives.
   * Resetting only in the Cancel handler left a successful save's values in place, and a second
   * Save would post the same record again.
   */
  useEffect(() => {
    if (!open) setFields(BLANK);
  }, [open]);

  /** Moves focus into the dialog on open, and closes it on Escape. */
  useEffect(() => {
    if (!open) return;

    firstField.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (state.kind === "closed") return null;

  const busy = state.kind === "submitting";

  function submit(event: React.FormEvent) {
    event.preventDefault();

    const missing = REQUIRED.filter(({ field }) => !fields[field].trim());
    if (missing.length > 0) {
      const names = missing.map(({ label }) => label).join(", ");
      onInvalid(`${names} ${missing.length > 1 ? "are" : "is"} required`);
      return;
    }

    onSubmit({
      company: fields.company.trim(),
      role: fields.role.trim(),
      location: fields.location.trim(),
      source: fields.source.trim(),
      url: fields.url.trim(),
      status: fields.status,
      applied_date: fields.applied_date || null,
      notes: fields.notes,
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "oklch(28% 0.02 60 / 38%)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-application-heading"
        className="max-h-full w-[440px] overflow-auto rounded-[10px] border border-line bg-panel p-5"
      >
        <h2
          id="add-application-heading"
          className="font-display text-base font-bold"
        >
          Add application
        </h2>

        <div className="mt-4 grid gap-3">
          <Field
            ref={firstField}
            label="Company"
            required
            value={fields.company}
            onChange={(value) => setFields({ ...fields, company: value })}
          />
          <Field
            label="Role"
            required
            value={fields.role}
            onChange={(value) => setFields({ ...fields, role: value })}
          />
          <Field
            label="Location"
            required
            value={fields.location}
            onChange={(value) => setFields({ ...fields, location: value })}
          />
          <Field
            label="Source"
            required
            placeholder="LinkedIn, referral, company site..."
            value={fields.source}
            onChange={(value) => setFields({ ...fields, source: value })}
          />
          <Field
            label="Posting URL"
            placeholder="https://"
            value={fields.url}
            onChange={(value) => setFields({ ...fields, url: value })}
          />

          <label className="grid gap-1.5">
            <span className="text-[11px] tracking-[0.04em] text-ink-dim uppercase">
              Status
            </span>
            <select
              value={fields.status}
              onChange={(event) =>
                setFields({ ...fields, status: event.target.value as Status })
              }
              className="rounded-md border border-line bg-page px-2.5 py-2 text-[13px] capitalize outline-none focus:border-accent"
            >
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>

          <Field
            label="Applied date"
            type="date"
            value={fields.applied_date}
            onChange={(value) => setFields({ ...fields, applied_date: value })}
          />

          <label className="grid gap-1.5">
            <span className="text-[11px] tracking-[0.04em] text-ink-dim uppercase">
              Notes
            </span>
            <textarea
              rows={3}
              value={fields.notes}
              onChange={(event) =>
                setFields({ ...fields, notes: event.target.value })
              }
              className="resize-y rounded-md border border-line bg-page px-2.5 py-2 text-[13px] outline-none focus:border-accent"
            />
          </label>
        </div>

        {(state.kind === "invalid" || state.kind === "failed") && (
          <p className="mt-3 text-xs text-danger" role="alert">
            {state.message}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-[7px] border border-line px-3.5 py-2 text-[13px] font-semibold text-ink-dim hover:border-line-strong hover:text-ink disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-[7px] bg-accent px-3.5 py-2 text-[13px] font-semibold text-page hover:bg-accent-bright disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * One labelled input.
 *
 * `required` draws the asterisk and nothing else — the native attribute is left off so the
 * browser cannot block submission with its own message, and `REQUIRED` above is what is actually
 * enforced. A field marked here has to be listed there too.
 */
function Field({
  ref,
  label,
  value,
  onChange,
  required,
  placeholder,
  type = "text",
}: {
  ref?: React.Ref<HTMLInputElement>;
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="text-[11px] tracking-[0.04em] text-ink-dim uppercase">
        {label}
        {required && <span className="ml-0.5 text-accent">*</span>}
      </span>
      <input
        ref={ref}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-line bg-page px-2.5 py-2 text-[13px] outline-none placeholder:text-ink-faint focus:border-accent"
      />
    </label>
  );
}
