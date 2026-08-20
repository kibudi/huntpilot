import { useEffect, useState } from "react";

import { ApiError, fetchProfile, saveProfile } from "../api";
import type { FieldError, ProfileState } from "../state";
import type { Profile } from "../types";

/**
 * The search profile editor.
 *
 * Every rule about what makes a profile usable lives in the API, and this form knows none of them.
 * It edits text, posts the whole profile, and renders whatever comes back — a stored profile or a
 * list of complaints. A copy of the rules here would be a second answer to "is this search worth
 * running", and the copy is the one that would fall behind.
 *
 * The form refills from the response rather than keeping what was typed, so the normalisation the
 * API applied — fragments lower-cased, an omitted vocabulary filled in — is visible instead of
 * silently different from what is on screen.
 */
export function ProfileForm() {
  const [state, setState] = useState<ProfileState>({ kind: "loading" });

  useEffect(() => {
    void (async () => {
      try {
        setState({ kind: "ready", draft: await fetchProfile() });
      } catch (error) {
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : "Unknown error",
        });
      }
    })();
  }, []);

  /** Applies one edit, dropping any rejection the previous draft collected. */
  function edit(changes: Partial<Profile>) {
    if (state.kind === "loading" || state.kind === "error") return;
    setState({ kind: "ready", draft: { ...state.draft, ...changes } });
  }

  async function save() {
    if (state.kind === "loading" || state.kind === "error") return;
    const { draft } = state;
    setState({ kind: "saving", draft });
    try {
      setState({ kind: "saved", draft: await saveProfile(draft) });
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        setState({ kind: "rejected", draft, errors: fieldErrors(error.detail) });
        return;
      }
      setState({
        kind: "error",
        message: error instanceof Error ? error.message : "Unknown error",
      });
    }
  }

  if (state.kind === "loading") {
    return <p className="text-sm text-ink-dim">Loading the profile…</p>;
  }
  if (state.kind === "error") {
    return <p className="text-sm text-danger">Could not load the profile — {state.message}</p>;
  }

  const { draft } = state;
  const errors = state.kind === "rejected" ? state.errors : [];
  const busy = state.kind === "saving";

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h2 className="font-display text-lg text-ink">The search</h2>
        <p className="mt-1 text-sm text-ink-dim">
          What every sweep filters by. Saving replaces the whole profile, and takes effect on the
          next sweep with no restart.
        </p>
      </div>

      <Panel title="Where" hint="Matched against the posting's location, lower-cased.">
        <ListField
          label="Local spellings"
          hint="Cities and districts worth commuting to, however the boards write them."
          value={draft.local_fragments}
          onChange={(local_fragments) => edit({ local_fragments })}
          error={errorFor(errors, "local_fragments")}
        />
        <ListField
          label="Remote wordings"
          hint="What a board says when a role is advertised as remote."
          value={draft.remote_fragments}
          onChange={(remote_fragments) => edit({ remote_fragments })}
          error={errorFor(errors, "remote_fragments")}
        />
      </Panel>

      <Panel title="Which roles" hint="Patterns are regular expressions, compiled by the API.">
        <MapField
          label="Role families"
          hint="Tried in the order listed. A posting matching none of them is dropped."
          keyLabel="family"
          value={draft.role_families}
          onChange={(role_families) => edit({ role_families })}
          error={errorFor(errors, "role_families")}
        />
        <TextField
          label="Seniority markers"
          hint="One pattern. A title matching it is too senior and is dropped."
          value={draft.seniority_markers}
          onChange={(seniority_markers) => edit({ seniority_markers })}
          error={errorFor(errors, "seniority_markers")}
        />
      </Panel>

      <Panel title="Which stack" hint="Read from the posting's description, not its title.">
        <MapField
          label="Known"
          hint="Technologies already worked in. These count for a posting."
          keyLabel="technology"
          value={draft.known}
          onChange={(known) => edit({ known })}
          error={errorFor(errors, "known")}
        />
        <MapField
          label="Unknown"
          hint="Technologies not worked in. These count against a posting."
          keyLabel="technology"
          value={draft.unknown}
          onChange={(unknown) => edit({ unknown })}
          error={errorFor(errors, "unknown")}
        />
      </Panel>

      <Panel title="Thresholds">
        <NumberField
          label="Minimum stack score"
          hint="Share of a posting's named technologies that must be known — a fraction of one, not a percentage."
          value={draft.min_tech_score}
          step={0.05}
          onChange={(min_tech_score) => edit({ min_tech_score })}
          error={errorFor(errors, "min_tech_score")}
        />
        <NumberField
          label="Most years asked for"
          hint="A posting asking for more experience than this is dropped."
          value={draft.max_years}
          step={1}
          onChange={(max_years) => edit({ max_years })}
          error={errorFor(errors, "max_years")}
        />
      </Panel>

      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy}
          className="rounded-md bg-accent px-4 py-2 font-medium text-page transition hover:bg-accent-bright disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Saving…" : "Save the profile"}
        </button>

        {state.kind === "saved" && (
          <span className="text-sm text-ink-dim">Saved. The next sweep will use it.</span>
        )}
        {state.kind === "rejected" && (
          <span className="text-sm text-danger">
            Not saved — {state.errors.length} problem
            {state.errors.length === 1 ? "" : "s"} below. The stored profile is unchanged.
          </span>
        )}
      </div>
    </section>
  );
}

/** A titled group of fields. */
function Panel({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-panel p-5">
      <h3 className="font-display text-base text-ink">{title}</h3>
      {hint && <p className="mt-0.5 text-xs text-ink-dim">{hint}</p>}
      <div className="mt-4 flex flex-col gap-4">{children}</div>
    </div>
  );
}

/** The label, hint and complaint that sit around every field. */
function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm font-medium text-ink">{label}</span>
      {hint && <span className="text-xs text-ink-dim">{hint}</span>}
      {children}
      {error && <span className="text-xs text-danger">{error}</span>}
    </label>
  );
}

/** Shared input styling, so a rejected field looks rejected wherever it is. */
function inputClass(error?: string): string {
  return `rounded-md border bg-raised px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent ${
    error ? "border-danger" : "border-line"
  }`;
}

/** One line of text. */
function TextField({
  label,
  hint,
  value,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass(error)}
      />
    </Field>
  );
}

/** A number, kept a number rather than a string so the API is not sent `"0.8"`. */
function NumberField({
  label,
  hint,
  value,
  step,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  value: number;
  step: number;
  onChange: (value: number) => void;
  error?: string;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.valueAsNumber)}
        className={`${inputClass(error)} w-40`}
      />
    </Field>
  );
}

/**
 * A list of short strings, edited one per line.
 *
 * A textarea rather than a row of inputs with add and remove buttons: these are lists of city
 * names, and typing one per line is faster than clicking Add sixty times. Blank lines are dropped
 * on the way out, so a trailing newline is not sent as an empty fragment that matches everything.
 */
function ListField({
  label,
  hint,
  value,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  value: string[];
  onChange: (value: string[]) => void;
  error?: string;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      <textarea
        rows={Math.min(10, Math.max(3, value.length + 1))}
        value={value.join("\n")}
        onChange={(event) =>
          onChange(
            event.target.value
              .split("\n")
              .map((line) => line.trim())
              .filter((line) => line.length > 0),
          )
        }
        className={`${inputClass(error)} font-mono`}
      />
    </Field>
  );
}

/**
 * A name-to-pattern map, edited as `name = pattern` lines.
 *
 * One text area rather than paired inputs, for the same reason as `ListField` and one more: these
 * maps are what `profile.json` holds, and editing them in the same shape they are written in means
 * a person moving between the file and this form is reading one format rather than two.
 *
 * A line with no `=` is kept as a name with an empty pattern rather than dropped, so half-typed
 * input does not disappear under the cursor. The API refuses an empty pattern and says which entry
 * it was.
 */
function MapField({
  label,
  hint,
  keyLabel,
  value,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  keyLabel: string;
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
  error?: string;
}) {
  const text = Object.entries(value)
    .map(([name, pattern]) => `${name} = ${pattern}`)
    .join("\n");

  return (
    <Field label={label} hint={`${hint ?? ""} One per line, as ${keyLabel} = pattern.`.trim()} error={error}>
      <textarea
        rows={Math.min(14, Math.max(3, Object.keys(value).length + 1))}
        value={text}
        onChange={(event) => onChange(parseMap(event.target.value))}
        className={`${inputClass(error)} font-mono`}
      />
    </Field>
  );
}

/** Reads `name = pattern` lines back into a map, keeping the order they were written in. */
function parseMap(text: string): Record<string, string> {
  const entries: Record<string, string> = {};
  for (const line of text.split("\n")) {
    if (line.trim().length === 0) continue;
    const split = line.indexOf("=");
    const name = (split === -1 ? line : line.slice(0, split)).trim();
    if (name.length === 0) continue;
    entries[name] = split === -1 ? "" : line.slice(split + 1).trim();
  }
  return entries;
}

/**
 * Turns FastAPI's `detail` into one complaint per field.
 *
 * Two rejections arrive at this endpoint with `loc` paths that differ by one entry. A body of the
 * wrong shape is caught by FastAPI itself and located from the request inwards, as
 * `["body", "known", "sql"]`; a body of the right shape holding an unusable search is caught by
 * the profile model and located from the profile inwards, as `["known", "sql"]`. A leading `body`
 * is therefore dropped rather than assumed either way — reading the field from a fixed position
 * attributes half the complaints to the wrong input, and it is the half that names a bad pattern.
 *
 * Shape is checked rather than assumed, because this is the one place a malformed error body would
 * turn a rejection into a crash and hide the reason the save failed.
 */
function fieldErrors(detail: unknown): FieldError[] {
  if (!Array.isArray(detail)) return [];

  return detail.flatMap((entry): FieldError[] => {
    if (typeof entry !== "object" || entry === null) return [];
    const { loc, msg } = entry as { loc?: unknown; msg?: unknown };
    if (typeof msg !== "string") return [];

    const path = Array.isArray(loc) ? loc.map(String) : [];
    const inside = path[0] === "body" ? path.slice(1) : path;
    const rest = inside.slice(1).join(".");
    return [{ field: inside[0] ?? "", detail: rest ? `${rest}: ${msg}` : msg }];
  });
}

/** The complaints against one field, joined into a line the form can show under it. */
function errorFor(errors: FieldError[], field: string): string | undefined {
  const matching = errors.filter((error) => error.field === field);
  if (matching.length === 0) return undefined;
  return matching.map((error) => error.detail).join("; ");
}
