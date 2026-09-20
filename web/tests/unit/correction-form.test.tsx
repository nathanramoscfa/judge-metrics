// web/tests/unit/correction-form.test.tsx
// The corrections form: submit stays disabled until every field validates,
// the prefilled target is read-only, the consent line is present, a 202
// from the route handler hands the id on (the page navigates to
// /corrections/received?id=…), the handler's or the API's 422 shows field
// errors beside the fields, a 429 shows the wait, and the body posted to
// the route handler carries the allow-listed fields only.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CONSENT_TEXT, CorrectionForm } from "@/components/correction-form";
import { CORRECTIONS_ROUTE } from "@/lib/corrections";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn() }),
}));

const JUDGE_ID = "6395ea5c-a9c0-41ee-b36f-1e492520e36f";
const REASON = "The commission date shown is 2009-08-06 but the source record says 2009-08-08.";
const CONTACT = "requester@example.invalid";
const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  push.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CorrectionForm", () => {
  it("renders the prefilled target read-only with the consent line and a disabled submit", () => {
    render(<CorrectionForm target={{ type: "judge", id: JUDGE_ID }} label="Judge Example" />);
    expect(screen.getByTestId("target-type")).toHaveValue("Judge");
    expect(screen.getByTestId("target-type")).toHaveAttribute("readonly");
    expect(screen.getByTestId("target-id")).toHaveValue(JUDGE_ID);
    expect(screen.getByTestId("target-id")).toHaveAttribute("readonly");
    expect(screen.getByTestId("target-label")).toHaveTextContent("Judge Example");
    expect(screen.getByTestId("consent")).toHaveTextContent(CONSENT_TEXT);
    expect(screen.getByTestId("submit-correction")).toBeDisabled();
    expect(screen.getByTestId("submit-status")).toHaveTextContent("Fill in every required field");
    // No file input anywhere: supporting material is a URL field.
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(screen.getByTestId("supporting-material")).toHaveAttribute("type", "url");
  });

  it("enables submit only once the reason and contact validate, and shows the reason limit", async () => {
    const user = userEvent.setup();
    render(<CorrectionForm target={{ type: "judge", id: JUDGE_ID }} />);
    const submit = screen.getByTestId("submit-correction");
    await user.type(screen.getByTestId("reason"), "too short");
    await user.type(screen.getByTestId("contact"), CONTACT);
    await user.tab();
    expect(submit).toBeDisabled();
    expect(screen.getByTestId("reason-count")).toHaveTextContent("9/4000");
    expect(screen.getAllByTestId("field-error")[0]).toHaveTextContent("at least 20 characters");
    await user.clear(screen.getByTestId("reason"));
    await user.type(screen.getByTestId("reason"), REASON);
    expect(submit).toBeEnabled();
    expect(screen.getByTestId("submit-status")).toHaveTextContent("Ready to send.");
  });

  it("posts the allow-listed body to the route handler and hands the id on", async () => {
    const user = userEvent.setup();
    const onSubmitted = vi.fn();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e", status: "received" }, { status: 202 }),
    );
    render(<CorrectionForm target={{ type: "case", id: JUDGE_ID }} onSubmitted={onSubmitted} />);
    await user.type(screen.getByTestId("reason"), REASON);
    await user.type(screen.getByTestId("contact"), CONTACT);
    await user.click(screen.getByTestId("submit-correction"));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith("0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(CORRECTIONS_ROUTE);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      target_type: "case",
      target_id: JUDGE_ID,
      reason: REASON,
      contact: CONTACT,
    });
  });

  it("navigates to the received page with the id when no callback is given", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e", status: "received" }, { status: 202 }),
    );
    render(<CorrectionForm target={{ type: "court", id: JUDGE_ID }} />);
    await user.type(screen.getByTestId("reason"), REASON);
    await user.type(screen.getByTestId("contact"), CONTACT);
    await user.click(screen.getByTestId("submit-correction"));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/corrections/received?id=0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"),
    );
  });

  it("shows the API's field errors from a 422 beside the fields", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          code: "validation_error",
          message: `target_id: no judge with id ${JUDGE_ID}; contact: String should have at most 320 characters`,
          request_id: "req-9",
        },
        { status: 422 },
      ),
    );
    render(<CorrectionForm target={{ type: "judge", id: JUDGE_ID }} />);
    await user.type(screen.getByTestId("reason"), REASON);
    await user.type(screen.getByTestId("contact"), CONTACT);
    await user.click(screen.getByTestId("submit-correction"));
    const alert = await screen.findByTestId("submit-error");
    expect(alert).toHaveTextContent("correct the fields marked below");
    const errors = screen.getAllByTestId("field-error").map((node) => node.textContent);
    expect(errors).toContain(`no judge with id ${JUDGE_ID}`);
    expect(errors).toContain("String should have at most 320 characters");
    expect(screen.getByTestId("target-id")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows the handler's per-field errors map and clears it on edit", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "validation_error", message: "reason: x", request_id: null, errors: { reason: "Describe the error." } },
        { status: 422 },
      ),
    );
    render(<CorrectionForm target={{ type: "judge", id: JUDGE_ID }} />);
    await user.type(screen.getByTestId("reason"), REASON);
    await user.type(screen.getByTestId("contact"), CONTACT);
    await user.click(screen.getByTestId("submit-correction"));
    await screen.findByTestId("submit-error");
    expect(screen.getByTestId("field-error")).toHaveTextContent("Describe the error.");
    await user.type(screen.getByTestId("reason"), " More.");
    expect(screen.queryByTestId("submit-error")).toBeNull();
  });

  it("reports a 429 with the wait and a 503 as unavailable", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "rate_limited", message: "too many", request_id: "r" },
        { status: 429, headers: { "content-type": "application/json", "retry-after": "17" } },
      ),
    );
    render(<CorrectionForm target={{ type: "judge", id: JUDGE_ID }} />);
    await user.type(screen.getByTestId("reason"), REASON);
    await user.type(screen.getByTestId("contact"), CONTACT);
    await user.click(screen.getByTestId("submit-correction"));
    const alert = await screen.findByTestId("submit-error");
    expect(alert).toHaveTextContent("Too many correction requests");
    expect(alert).toHaveTextContent("17 seconds");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "corrections_unavailable", message: "not accepted", request_id: "r" }, { status: 503 }),
    );
    await user.type(screen.getByTestId("reason"), " Again.");
    await user.click(screen.getByTestId("submit-correction"));
    expect(await screen.findByTestId("submit-error")).toHaveTextContent("not being accepted right now");
  });

  it("offers an editable target when nothing is prefilled", async () => {
    const user = userEvent.setup();
    render(<CorrectionForm target={null} />);
    const type = screen.getByTestId("target-type");
    expect(type.tagName).toBe("SELECT");
    expect(within(type).getAllByRole("option")).toHaveLength(5);
    await user.selectOptions(type, "court");
    await user.type(screen.getByTestId("target-id"), "not-a-uuid");
    await user.tab();
    expect(screen.getByTestId("field-error")).toHaveTextContent("must be a UUID");
    expect(screen.getByTestId("submit-correction")).toBeDisabled();
  });
});
