// web/components/correction-form.tsx
// The data-correction form (client component). The target type and id are
// read-only when the page prefilled them from the "Report a data error"
// link; otherwise they are editable. The reason textarea and the contact
// input carry the API's length limits (lib/corrections.ts), the supporting
// material is an optional http(s) URL — there is no file upload — and the
// consent line states that the contact is stored encrypted and used only to
// answer the request. Submit stays disabled until the values validate; the
// form posts JSON to the route handler (/api/corrections, same origin, never
// the API directly), shows the pending state, renders the handler's or the
// API's field errors beside the fields, and on 202 navigates to
// /corrections/received?id=… with the id.
"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  CORRECTION_TARGET_TYPES,
  CORRECTIONS_ROUTE,
  type CorrectionFormValues,
  type CorrectionTargetType,
  type FieldErrors,
  LIMITS,
  TARGET_TYPE_LABELS,
  fieldErrorsFromMessage,
  isCorrectionTargetType,
  validateCorrection,
} from "@/lib/corrections";
import { cn } from "@/lib/utils";

export const CONSENT_TEXT =
  "Your contact is stored encrypted and used only to answer this request. It is never published, never shared, and never used for anything else.";

export interface CorrectionTarget {
  type: string;
  id: string;
}

type SubmitState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "error"; message: string; errors: FieldErrors; retryAfterSeconds: number | null };

interface HandlerError {
  code?: string;
  message?: string;
  errors?: FieldErrors;
}

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" data-testid="field-error" className="text-xs text-destructive">
      {message}
    </p>
  );
}

const textareaClass =
  "min-h-32 w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive dark:bg-input/30";

export function CorrectionForm({
  target,
  label,
  onSubmitted,
}: {
  /** The prefilled target (read-only fields), or null for an editable target. */
  target: CorrectionTarget | null;
  /** The target's name as the page knew it; shown beside the read-only id. */
  label?: string | null;
  /** Called with the id instead of navigating (tests). */
  onSubmitted?: (id: string) => void;
}) {
  const router = useRouter();
  const baseId = useId();
  const prefilledType: CorrectionTargetType | null =
    target !== null && isCorrectionTargetType(target.type) ? target.type : null;
  const prefilled = prefilledType !== null;
  const [values, setValues] = useState<CorrectionFormValues>({
    target_type: prefilledType ?? "",
    target_id: prefilledType && target ? target.id : "",
    reason: "",
    contact: "",
    supporting_material: "",
  });
  const [touched, setTouched] = useState<Partial<Record<keyof CorrectionFormValues, boolean>>>({});
  const [state, setState] = useState<SubmitState>({ kind: "idle" });

  const validation = useMemo(() => validateCorrection(values), [values]);
  const clientErrors: FieldErrors = validation.ok ? {} : validation.errors;
  const serverErrors: FieldErrors = state.kind === "error" ? state.errors : {};
  const pending = state.kind === "pending";

  function shownError(field: keyof CorrectionFormValues): string | undefined {
    return serverErrors[field] ?? (touched[field] ? clientErrors[field] : undefined);
  }

  function update(field: keyof CorrectionFormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    if (state.kind === "error") setState({ kind: "idle" });
  }

  function touch(field: keyof CorrectionFormValues) {
    setTouched((current) => ({ ...current, [field]: true }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validation.ok || pending) return;
    setState({ kind: "pending" });
    let response: Response;
    try {
      response = await fetch(CORRECTIONS_ROUTE, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(validation.body),
      });
    } catch {
      setState({
        kind: "error",
        message: "The request could not be sent. Check your connection and try again.",
        errors: {},
        retryAfterSeconds: null,
      });
      return;
    }
    if (response.status === 202) {
      const accepted = (await response.json()) as { id: string };
      if (onSubmitted) onSubmitted(accepted.id);
      else router.push(`/corrections/received?id=${encodeURIComponent(accepted.id)}`);
      return;
    }
    let body: HandlerError = {};
    try {
      body = (await response.json()) as HandlerError;
    } catch {
      body = {};
    }
    const parsed = body.message ? fieldErrorsFromMessage(body.message) : {};
    const { form, ...fieldErrors } = parsed;
    const errors: FieldErrors = { ...fieldErrors, ...(body.errors ?? {}) };
    const retryAfter = Number.parseInt(response.headers.get("retry-after") ?? "", 10);
    const message =
      response.status === 429
        ? "Too many correction requests from this connection. Wait and try again."
        : response.status === 503
          ? "Corrections are not being accepted right now. Try again later."
          : Object.keys(errors).length > 0
            ? "Please correct the fields marked below."
            : (form ?? body.message ?? `The request failed (${response.status}).`);
    setState({
      kind: "error",
      message,
      errors,
      retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : null,
    });
  }

  const ids = {
    target_type: `${baseId}-target-type`,
    target_id: `${baseId}-target-id`,
    reason: `${baseId}-reason`,
    contact: `${baseId}-contact`,
    supporting_material: `${baseId}-supporting`,
  };

  return (
    <form
      onSubmit={submit}
      noValidate
      className="flex flex-col gap-5"
      data-testid="correction-form"
      aria-busy={pending}
    >
      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={pending}>
        <legend className="sr-only">The record this request is about</legend>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.target_type} className="text-sm font-medium">
            Record type
          </label>
          {prefilled ? (
            <Input
              id={ids.target_type}
              name="target_type"
              value={TARGET_TYPE_LABELS[prefilledType]}
              readOnly
              aria-readonly="true"
              data-testid="target-type"
              className="bg-muted/40"
            />
          ) : (
            <select
              id={ids.target_type}
              name="target_type"
              value={values.target_type}
              onChange={(event) => update("target_type", event.target.value)}
              onBlur={() => touch("target_type")}
              aria-invalid={shownError("target_type") ? true : undefined}
              aria-describedby={shownError("target_type") ? `${ids.target_type}-error` : undefined}
              data-testid="target-type"
              className="h-8 rounded-lg border border-input bg-background px-2 text-sm"
            >
              <option value="">Choose a record type</option>
              {CORRECTION_TARGET_TYPES.map((type) => (
                <option key={type} value={type}>
                  {TARGET_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          )}
          <FieldError id={`${ids.target_type}-error`} message={shownError("target_type")} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.target_id} className="text-sm font-medium">
            Record id
          </label>
          <Input
            id={ids.target_id}
            name="target_id"
            value={values.target_id}
            readOnly={prefilled}
            aria-readonly={prefilled ? "true" : undefined}
            onChange={prefilled ? undefined : (event) => update("target_id", event.target.value)}
            onBlur={() => touch("target_id")}
            aria-invalid={shownError("target_id") ? true : undefined}
            aria-describedby={shownError("target_id") ? `${ids.target_id}-error` : undefined}
            placeholder="The UUID in the page address"
            data-testid="target-id"
            className={cn("font-mono text-xs", prefilled && "bg-muted/40")}
          />
          {prefilled && label ? (
            <p className="text-xs text-muted-foreground" data-testid="target-label">
              {label}
            </p>
          ) : null}
          <FieldError id={`${ids.target_id}-error`} message={shownError("target_id")} />
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-4" disabled={pending}>
        <legend className="sr-only">The correction</legend>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.reason} className="text-sm font-medium">
            What is wrong, and what should the record say?
          </label>
          <textarea
            id={ids.reason}
            name="reason"
            value={values.reason}
            onChange={(event) => update("reason", event.target.value)}
            onBlur={() => touch("reason")}
            minLength={LIMITS.reason.min}
            maxLength={LIMITS.reason.max}
            required
            aria-invalid={shownError("reason") ? true : undefined}
            aria-describedby={`${ids.reason}-hint${shownError("reason") ? ` ${ids.reason}-error` : ""}`}
            data-testid="reason"
            className={textareaClass}
          />
          <p id={`${ids.reason}-hint`} className="text-xs text-muted-foreground">
            {LIMITS.reason.min}–{LIMITS.reason.max} characters. Name the source record where you
            can; an arrest is not a conviction and a prosecutor&apos;s dismissal is not a
            judge&apos;s, so say which fact is wrong.{" "}
            <span data-testid="reason-count" className="tabular-nums">
              {values.reason.trim().length}/{LIMITS.reason.max}
            </span>
          </p>
          <FieldError id={`${ids.reason}-error`} message={shownError("reason")} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.contact} className="text-sm font-medium">
            How can we reach you about this request?
          </label>
          <Input
            id={ids.contact}
            name="contact"
            type="text"
            autoComplete="email"
            value={values.contact}
            onChange={(event) => update("contact", event.target.value)}
            onBlur={() => touch("contact")}
            minLength={LIMITS.contact.min}
            maxLength={LIMITS.contact.max}
            required
            aria-invalid={shownError("contact") ? true : undefined}
            aria-describedby={`${ids.contact}-hint${shownError("contact") ? ` ${ids.contact}-error` : ""}`}
            placeholder="An email address"
            data-testid="contact"
          />
          <p id={`${ids.contact}-hint`} className="text-xs text-muted-foreground" data-testid="consent">
            {CONSENT_TEXT}
          </p>
          <FieldError id={`${ids.contact}-error`} message={shownError("contact")} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.supporting_material} className="text-sm font-medium">
            Supporting material (optional link)
          </label>
          <Input
            id={ids.supporting_material}
            name="supporting_material"
            type="url"
            inputMode="url"
            value={values.supporting_material}
            onChange={(event) => update("supporting_material", event.target.value)}
            onBlur={() => touch("supporting_material")}
            maxLength={LIMITS.supporting_material.max}
            aria-invalid={shownError("supporting_material") ? true : undefined}
            aria-describedby={`${ids.supporting_material}-hint${shownError("supporting_material") ? ` ${ids.supporting_material}-error` : ""}`}
            placeholder="https://"
            data-testid="supporting-material"
          />
          <p id={`${ids.supporting_material}-hint`} className="text-xs text-muted-foreground">
            An http(s) link to the docket entry, order, or record that shows the correct fact. No
            file upload: link to the public record instead.
          </p>
          <FieldError
            id={`${ids.supporting_material}-error`}
            message={shownError("supporting_material")}
          />
        </div>
      </fieldset>

      {state.kind === "error" ? (
        <div
          role="alert"
          data-testid="submit-error"
          className="rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm"
        >
          {state.message}
          {state.retryAfterSeconds !== null ? ` Try again in ${state.retryAfterSeconds} seconds.` : ""}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!validation.ok || pending} data-testid="submit-correction">
          {pending ? "Sending…" : "Send the correction request"}
        </Button>
        <p className="text-xs text-muted-foreground" aria-live="polite" data-testid="submit-status">
          {pending
            ? "Sending your request."
            : validation.ok
              ? "Ready to send."
              : "Fill in every required field to send."}
        </p>
      </div>
    </form>
  );
}
