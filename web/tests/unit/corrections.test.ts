// web/tests/unit/corrections.test.ts
// The corrections intake from the web side: the validator mirrors the API's
// limits, the link builder prefills the form, the 422 message parser names
// fields, and the route handler forwards exactly the allow-listed fields
// with the caller's X-Forwarded-For, returns the API's status and body
// (202 {id, status}; 422; 429 with Retry-After; 503 on a transport failure),
// and logs nothing of the body — every console method is spied and the
// reason and contact must appear in no call.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiResult, CorrectionAccepted, CorrectionIn } from "@/lib/api/client";
import {
  ALLOWED_FIELDS,
  LIMITS,
  correctionHref,
  fieldErrorsFromMessage,
  validateCorrection,
} from "@/lib/corrections";
import { allowListedBody, handleCorrectionPost } from "@/lib/corrections-handler";

const JUDGE_ID = "6395ea5c-a9c0-41ee-b36f-1e492520e36f";
const REASON = "The commission date shown is 2009-08-06 but the source record says 2009-08-08.";
const CONTACT = "requester@example.invalid";

const VALID = { target_type: "judge", target_id: JUDGE_ID, reason: REASON, contact: CONTACT };

describe("validateCorrection", () => {
  it("accepts a valid body and drops an empty supporting_material", () => {
    const result = validateCorrection({ ...VALID, supporting_material: "" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.body).toEqual(VALID);
      expect("supporting_material" in result.body).toBe(false);
    }
  });

  it("keeps a valid http(s) supporting_material and rejects other schemes", () => {
    const ok = validateCorrection({ ...VALID, supporting_material: "https://example.invalid/docket/1" });
    expect(ok.ok && ok.body.supporting_material).toBe("https://example.invalid/docket/1");
    const bad = validateCorrection({ ...VALID, supporting_material: "ftp://example.invalid/x" });
    expect(!bad.ok && bad.errors.supporting_material).toMatch(/http\(s\)/);
    const notUrl = validateCorrection({ ...VALID, supporting_material: "not a url" });
    expect(!notUrl.ok && notUrl.errors.supporting_material).toBeTruthy();
  });

  it("names every invalid field with the API's limits", () => {
    const result = validateCorrection({
      target_type: "person",
      target_id: "not-a-uuid",
      reason: "too short",
      contact: "ab",
      supporting_material: `https://example.invalid/${"x".repeat(LIMITS.supporting_material.max)}`,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(Object.keys(result.errors).sort()).toEqual([...ALLOWED_FIELDS].sort());
      expect(result.errors.reason).toContain(String(LIMITS.reason.min));
      expect(result.errors.contact).toContain(String(LIMITS.contact.min));
    }
  });

  it("rejects over-long and control-character values", () => {
    const long = validateCorrection({ ...VALID, reason: "x".repeat(LIMITS.reason.max + 1) });
    expect(!long.ok && long.errors.reason).toContain(String(LIMITS.reason.max));
    const control = validateCorrection({ ...VALID, reason: `${REASON}${String.fromCharCode(7)}` });
    expect(!control.ok && control.errors.reason).toMatch(/control characters/);
    const newline = validateCorrection({ ...VALID, reason: `${REASON}\nSecond line.` });
    expect(newline.ok).toBe(true);
  });

  it("treats a non-object as an empty body", () => {
    const result = validateCorrection("nope");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.reason).toBeTruthy();
  });
});

describe("correctionHref", () => {
  it("prefills the type, id, and a bounded label", () => {
    expect(correctionHref({ type: "judge", id: JUDGE_ID, label: "Judge Example" })).toBe(
      `/corrections?target_type=judge&target_id=${JUDGE_ID}&label=Judge+Example`,
    );
    expect(correctionHref({ type: "case", id: JUDGE_ID })).toBe(
      `/corrections?target_type=case&target_id=${JUDGE_ID}`,
    );
    const href = correctionHref({ type: "court", id: JUDGE_ID, label: "y".repeat(500) });
    expect(new URL(href, "http://localhost").searchParams.get("label")).toHaveLength(200);
  });
});

describe("fieldErrorsFromMessage", () => {
  it("splits the API's 422 message into per-field errors", () => {
    const errors = fieldErrorsFromMessage(
      "body.reason: String should have at least 20 characters; target_id: no judge with id x; something else",
    );
    expect(errors.reason).toBe("String should have at least 20 characters");
    expect(errors.target_id).toBe("no judge with id x");
    expect(errors.form).toBe("something else");
  });
});

describe("allowListedBody", () => {
  it("forwards exactly the allow-listed fields in order and nothing else", () => {
    const body = {
      contact: CONTACT,
      reason: REASON,
      target_id: JUDGE_ID,
      target_type: "judge",
      supporting_material: null,
      extra: "dropped",
      admin: true,
    } as unknown as CorrectionIn;
    const forwarded = allowListedBody(body);
    expect(Object.keys(forwarded)).toEqual(["target_type", "target_id", "reason", "contact"]);
    expect("extra" in forwarded).toBe(false);
    expect("admin" in forwarded).toBe(false);
  });
});

describe("handleCorrectionPost", () => {
  const consoleMethods = ["log", "info", "warn", "error", "debug", "trace"] as const;
  const spies: Array<{ mock: { calls: unknown[][] } }> = [];

  beforeEach(() => {
    for (const method of consoleMethods) {
      spies.push(vi.spyOn(console, method).mockImplementation(() => undefined));
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
    spies.length = 0;
  });

  function request(body: unknown, headers: Record<string, string> = {}): Request {
    return new Request("http://localhost:3000/api/corrections", {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: typeof body === "string" ? body : JSON.stringify(body),
    });
  }

  function accepted(): ApiResult<CorrectionAccepted> {
    return {
      ok: true,
      data: { id: "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e", status: "received", received_at: "2026-09-20T12:00:00Z" },
    };
  }

  function loggedText(): string {
    return spies
      .flatMap((spy) => spy.mock.calls)
      .map((call) => call.map((arg: unknown) => (typeof arg === "string" ? arg : JSON.stringify(arg))).join(" "))
      .join("\n");
  }

  it("forwards only the allow-listed fields with the caller's X-Forwarded-For and answers 202 {id, status}", async () => {
    const submit = vi.fn(async () => accepted());
    const response = await handleCorrectionPost(
      request({ ...VALID, supporting_material: "https://example.invalid/order.pdf", extra: "x", role: "admin" }, {
        "x-forwarded-for": "203.0.113.9, 10.0.0.1",
      }),
      submit,
    );
    expect(response.status).toBe(202);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ id: "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e", status: "received" });
    expect(submit).toHaveBeenCalledTimes(1);
    const [body, options] = submit.mock.calls[0] as unknown as [CorrectionIn, { forwardedFor: string | null }];
    expect(Object.keys(body)).toEqual([...ALLOWED_FIELDS]);
    expect(body).toEqual({ ...VALID, supporting_material: "https://example.invalid/order.pdf" });
    expect(options.forwardedFor).toBe("203.0.113.9, 10.0.0.1");
    expect(loggedText()).toBe("");
  });

  it("passes a null forwardedFor when the caller sent no chain", async () => {
    const submit = vi.fn(async () => accepted());
    await handleCorrectionPost(request(VALID), submit);
    const [, options] = submit.mock.calls[0] as unknown as [CorrectionIn, { forwardedFor: string | null }];
    expect(options.forwardedFor).toBeNull();
  });

  it("answers 422 with per-field errors before forwarding anything", async () => {
    const submit = vi.fn(async () => accepted());
    const response = await handleCorrectionPost(request({ ...VALID, reason: "short", contact: "" }), submit);
    expect(response.status).toBe(422);
    const body = await response.json();
    expect(body.code).toBe("validation_error");
    expect(body.errors.reason).toBeTruthy();
    expect(body.errors.contact).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
    expect(loggedText()).toBe("");
  });

  it("answers 422 for a body that is not JSON", async () => {
    const submit = vi.fn(async () => accepted());
    const response = await handleCorrectionPost(request("{not json"), submit);
    expect(response.status).toBe(422);
    expect(submit).not.toHaveBeenCalled();
  });

  it("returns the API's error body and status, with Retry-After on 429", async () => {
    const submit = vi.fn(
      async (): Promise<ApiResult<CorrectionAccepted>> => ({
        ok: false,
        error: { status: 429, code: "rate_limited", message: "too many requests", requestId: "req-1", retryAfterSeconds: 42 },
      }),
    );
    const response = await handleCorrectionPost(request(VALID), submit);
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("42");
    expect(await response.json()).toEqual({ code: "rate_limited", message: "too many requests", request_id: "req-1" });
  });

  it("maps the API's 422 (an unknown target) through unchanged", async () => {
    const submit = vi.fn(
      async (): Promise<ApiResult<CorrectionAccepted>> => ({
        ok: false,
        error: {
          status: 422,
          code: "validation_error",
          message: `target_id: no judge with id ${JUDGE_ID}`,
          requestId: "req-2",
          retryAfterSeconds: null,
        },
      }),
    );
    const response = await handleCorrectionPost(request(VALID), submit);
    expect(response.status).toBe(422);
    expect((await response.json()).message).toContain("target_id");
  });

  it("answers 503 when the API is unreachable and logs nothing of the body", async () => {
    const submit = vi.fn(
      async (): Promise<ApiResult<CorrectionAccepted>> => ({
        ok: false,
        error: { status: 0, code: "network_error", message: "fetch failed", requestId: null, retryAfterSeconds: null },
      }),
    );
    const response = await handleCorrectionPost(request(VALID), submit);
    expect(response.status).toBe(503);
    expect((await response.json()).code).toBe("network_error");
    const logged = loggedText();
    expect(logged).not.toContain(REASON);
    expect(logged).not.toContain(CONTACT);
    expect(logged).toBe("");
  });

  it("never lets the reason or contact into a response body other than the API's own", async () => {
    const submit = vi.fn(async () => accepted());
    const response = await handleCorrectionPost(request(VALID), submit);
    const text = await response.text();
    expect(text).not.toContain(REASON);
    expect(text).not.toContain(CONTACT);
  });
});
