// web/lib/corrections.ts
// The corrections intake as the web tier sees it: the API's field limits
// (CorrectionIn in docs/openapi.json) mirrored so the form can validate
// before it posts and the route handler can validate before it forwards,
// the allow-list of body fields the handler forwards (an explicit list —
// never a spread of the caller's body), the "Report a data error" link
// builder every page uses, and the parser that turns the API's 422 message
// ("reason: ...; contact: ...") into per-field errors for the form.
import type { CorrectionIn } from "@/lib/api/client";

export const CORRECTION_TARGET_TYPES = ["judge", "court", "case", "metric_observation"] as const;
export type CorrectionTargetType = (typeof CORRECTION_TARGET_TYPES)[number];

export const TARGET_TYPE_LABELS: Record<CorrectionTargetType, string> = {
  judge: "Judge",
  court: "Court",
  case: "Case",
  metric_observation: "Published number (metric observation)",
};

/** CorrectionIn's limits, from the OpenAPI document; the API enforces them again. */
export const LIMITS = {
  reason: { min: 20, max: 4000 },
  contact: { min: 3, max: 320 },
  supporting_material: { max: 2000 },
} as const;

/** The body fields the route handler forwards to the API, and nothing else. */
export const ALLOWED_FIELDS = [
  "target_type",
  "target_id",
  "reason",
  "contact",
  "supporting_material",
] as const;
export type CorrectionField = (typeof ALLOWED_FIELDS)[number];

/** The route handler the form posts to (never the API directly from the browser). */
export const CORRECTIONS_ROUTE = "/api/corrections";

/** What the form holds: every field as a string, the optional URL empty when absent. */
export interface CorrectionFormValues {
  target_type: string;
  target_id: string;
  reason: string;
  contact: string;
  supporting_material: string;
}

export type FieldErrors = Partial<Record<CorrectionField, string>>;

export type CorrectionValidation =
  | { ok: true; body: CorrectionIn }
  | { ok: false; errors: FieldErrors };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** The API rejects control characters other than tab, newline, and carriage return. */
function hasControlCharacter(value: string): boolean {
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if ((code < 32 && code !== 9 && code !== 10 && code !== 13) || code === 127) return true;
  }
  return false;
}

export function isCorrectionTargetType(value: string): value is CorrectionTargetType {
  return (CORRECTION_TARGET_TYPES as readonly string[]).includes(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Validate form values (or a parsed request body) against the API's limits.
 * Unknown keys are ignored here and dropped by the handler; the result body
 * carries exactly the allow-listed fields, `supporting_material` only when
 * given.
 */
export function validateCorrection(input: unknown): CorrectionValidation {
  const values = (typeof input === "object" && input !== null ? input : {}) as Record<
    string,
    unknown
  >;
  const errors: FieldErrors = {};
  const targetType = text(values.target_type);
  const targetId = text(values.target_id);
  const reason = text(values.reason);
  const contact = text(values.contact);
  const supporting = text(values.supporting_material);

  if (!isCorrectionTargetType(targetType)) {
    errors.target_type = `Choose one of: ${CORRECTION_TARGET_TYPES.join(", ")}.`;
  }
  if (!UUID.test(targetId)) {
    errors.target_id = "The target id must be a UUID (the id in the page address).";
  }
  if (reason.length < LIMITS.reason.min) {
    errors.reason = `Describe the error in at least ${LIMITS.reason.min} characters.`;
  } else if (reason.length > LIMITS.reason.max) {
    errors.reason = `Keep the description under ${LIMITS.reason.max} characters.`;
  } else if (hasControlCharacter(reason)) {
    errors.reason = "The description must not contain control characters.";
  }
  if (contact.length < LIMITS.contact.min) {
    errors.contact = `Give a way to reach you (at least ${LIMITS.contact.min} characters).`;
  } else if (contact.length > LIMITS.contact.max) {
    errors.contact = `Keep the contact under ${LIMITS.contact.max} characters.`;
  } else if (hasControlCharacter(contact)) {
    errors.contact = "The contact must not contain control characters.";
  }
  if (supporting) {
    if (supporting.length > LIMITS.supporting_material.max) {
      errors.supporting_material = `Keep the link under ${LIMITS.supporting_material.max} characters.`;
    } else {
      let url: URL | null = null;
      try {
        url = new URL(supporting);
      } catch {
        url = null;
      }
      if (!url || (url.protocol !== "http:" && url.protocol !== "https:")) {
        errors.supporting_material = "The supporting material must be an http(s) link.";
      }
    }
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  const body: CorrectionIn = {
    target_type: targetType as CorrectionTargetType,
    target_id: targetId,
    reason,
    contact,
  };
  if (supporting) body.supporting_material = supporting;
  return { ok: true, body };
}

/** `/corrections?target_type=judge&target_id=…&label=…`: the "Report a data error" link. */
export function correctionHref(target: {
  type: CorrectionTargetType;
  id: string;
  label?: string | null;
}): string {
  const query = new URLSearchParams({ target_type: target.type, target_id: target.id });
  if (target.label) query.set("label", target.label.slice(0, 200));
  return `/corrections?${query.toString()}`;
}

/**
 * The API's 422 message names each offending field ("reason: String should
 * have at least 20 characters; target_id: no judge with id …"); split it into
 * per-field errors so the form can show them beside the field. Anything
 * that names no known field stays under `form`.
 */
export function fieldErrorsFromMessage(message: string): FieldErrors & { form?: string } {
  const errors: FieldErrors & { form?: string } = {};
  const rest: string[] = [];
  for (const part of message.split(";")) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const match = /^(?:body\.)?([a-z_]+):\s*([^]+)$/.exec(trimmed);
    const field = match?.[1];
    if (field && (ALLOWED_FIELDS as readonly string[]).includes(field)) {
      errors[field as CorrectionField] = match[2];
    } else {
      rest.push(trimmed);
    }
  }
  if (rest.length > 0) errors.form = rest.join("; ");
  return errors;
}
