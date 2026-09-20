// web/lib/corrections-handler.ts
// The corrections route handler's logic (app/api/corrections/route.ts
// exports it as POST), kept here so Vitest can drive it with a Request and
// a stubbed API. It parses the JSON body, validates it against the API's
// limits, forwards exactly the allow-listed fields to POST /api/v1/corrections
// with the caller's X-Forwarded-For chain (when present), and answers with
// `{id, status}` or the API's error body under the API's status (422, 429
// with Retry-After, 503). It logs nothing: no line, no field, no error text
// — the reason and the contact never leave this function except towards
// the API, and the response never echoes them.
import { submitCorrection, type ApiError, type CorrectionIn } from "@/lib/api/client";
import { ALLOWED_FIELDS, type FieldErrors, validateCorrection } from "@/lib/corrections";

export type SubmitCorrection = typeof submitCorrection;

/** The handler's own error body: the API's shape plus per-field errors when it validated. */
export interface CorrectionErrorResponse {
  code: string;
  message: string;
  request_id: string | null;
  errors?: FieldErrors;
}

export interface CorrectionAcceptedResponse {
  id: string;
  status: "received";
}

const NO_STORE = { "Cache-Control": "no-store" } as const;

function errorResponse(status: number, body: CorrectionErrorResponse, retryAfter?: number | null) {
  const headers: Record<string, string> = { ...NO_STORE };
  if (retryAfter !== null && retryAfter !== undefined) headers["Retry-After"] = String(retryAfter);
  return Response.json(body, { status, headers });
}

/** Exactly the allow-listed fields, in this order: never a spread of the caller's body. */
export function allowListedBody(body: CorrectionIn): CorrectionIn {
  const forwarded: Record<string, unknown> = {};
  for (const field of ALLOWED_FIELDS) {
    const value = body[field];
    if (value !== undefined && value !== null && value !== "") forwarded[field] = value;
  }
  return forwarded as unknown as CorrectionIn;
}

/** A transport failure is a 503 the browser can act on; every other status is the API's. */
function statusFor(error: ApiError): number {
  return error.status === 0 ? 503 : error.status;
}

export async function handleCorrectionPost(
  request: Request,
  submit: SubmitCorrection = submitCorrection,
): Promise<Response> {
  let parsed: unknown;
  try {
    parsed = await request.json();
  } catch {
    return errorResponse(422, {
      code: "validation_error",
      message: "the request body must be a JSON object",
      request_id: null,
    });
  }
  const validation = validateCorrection(parsed);
  if (!validation.ok) {
    return errorResponse(422, {
      code: "validation_error",
      message: Object.entries(validation.errors)
        .map(([field, text]) => `${field}: ${text}`)
        .join("; "),
      request_id: null,
      errors: validation.errors,
    });
  }
  const forwardedFor = request.headers.get("x-forwarded-for");
  const result = await submit(allowListedBody(validation.body), { forwardedFor });
  if (!result.ok) {
    return errorResponse(
      statusFor(result.error),
      {
        code: result.error.code,
        message: result.error.message,
        request_id: result.error.requestId,
      },
      result.error.retryAfterSeconds,
    );
  }
  const accepted: CorrectionAcceptedResponse = { id: result.data.id, status: result.data.status };
  return Response.json(accepted, { status: 202, headers: NO_STORE });
}
