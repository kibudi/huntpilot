import { useState } from "react";
import type { DialogState } from "../state";
import { STATUSES, type ApplicationCreate, type Status } from "../types";

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

const REQUIRED: (keyof typeof BLANK)[] = [
  "company",
  "role",
  "location",
  "source",
  "url",
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

  if (state.kind === "closed") return null;

  const busy = state.kind === "submitting";

  function close() {
    setFields(BLANK);
    onClose();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();

    const missing = REQUIRED.filter((name) => !fields[name].trim());
    if (missing.length > 0) {
      onInvalid(`${missing.join(", ")} ${missing.length > 1 ? "are" : "is"} required`);
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
      style={{ background: "oklch(10% 0.01 250 / 65%)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) close();
      }}
    >
      <form
        onSubmit={submit}
        className="max-h-full w-[440px] overflow-auto rounded-[10px] border border-line bg-panel p-5"
      >
        <h2 className="font-display text-base font-bold">Add application</h2>

        <div className="mt-4 grid gap-3">
          <Field
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
            required
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
            onClick={close}
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

function Field({
  label,
  value,
  onChange,
  required,
  placeholder,
  type = "text",
}: {
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
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-line bg-page px-2.5 py-2 text-[13px] outline-none placeholder:text-ink-faint focus:border-accent"
      />
    </label>
  );
}
