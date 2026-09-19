// web/lib/api/client.ts
// The typed API client: openapi-fetch over the types generated from
// ../docs/openapi.json (`pnpm generate:api`). Server components call the
// helpers below on the server; every helper returns an ApiResult instead of
// throwing, so a page can render an error state with the request id. The
// base URL is public by design (NEXT_PUBLIC_*); no other JUDGEMETRICS_
// variable is read anywhere in the web tier.
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type JudgeDetail = Schemas["JudgeDetail"];
export type JudgeSummary = Schemas["JudgeSummary"];
export type JudgeStatus = JudgeDetail["status"];
export type ServiceRecord = Schemas["ServiceRecord"];
export type CourtDetail = Schemas["CourtDetail"];
export type CourtSummary = Schemas["CourtSummary"];
export type JurisdictionDetail = Schemas["JurisdictionDetail"];
export type JurisdictionSummary = Schemas["JurisdictionSummary"];
export type Provenance = Schemas["Provenance"];
export type CoverageWindow = Schemas["CoverageWindow"];
export type SearchResponse = Schemas["SearchResponse"];
export type SearchResult = Schemas["SearchResult"];
export type CaseSummary = Schemas["CaseSummary"];
export type CaseDetail = Schemas["CaseDetail"];
export type CaseParty = Schemas["CasePartyOut"];
export type Assignment = Schemas["AssignmentOut"];
export type Charge = Schemas["ChargeOut"];
export type Decision = Schemas["DecisionOut"];
export type PretrialRelease = Schemas["PretrialReleaseOut"];
export type Sentence = Schemas["SentenceOut"];
export type Timeline = Schemas["Timeline"];
export type TimelineEntry = Schemas["TimelineEntry"];
export type TimelineKind = TimelineEntry["kind"];
export type ActorType = Schemas["ActorType"];
export type Coverage = Schemas["Coverage"];
export type CoverageSource = Schemas["CoverageSource"];
export type ErrorBody = Schemas["ErrorBody"];
// The metrics surface (Phase 3 Step 3).
export type Registry = Schemas["Registry"];
export type MetricDefinition = Schemas["MetricDefinitionOut"];
export type Observation = Schemas["Observation"];
export type SubjectMetrics = Schemas["SubjectMetrics"];
export type ComparePage = Schemas["ComparePage"];
export type CompareRow = Schemas["CompareRow"];
export type CompareCohort = Schemas["CompareCohort"];
export type ObservationProvenance = Schemas["ObservationProvenance"];
export type CorrectionIn = Schemas["CorrectionIn"];
export type CorrectionAccepted = Schemas["CorrectionAccepted"];
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
};

export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** The API origin, inlined at build time from NEXT_PUBLIC_API_BASE_URL. */
export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") ||
  DEFAULT_API_BASE_URL;

/** A failed call: the API's error envelope, or a transport failure (status 0). */
export interface ApiError {
  status: number;
  code: string;
  message: string;
  requestId: string | null;
  /** Seconds to wait, from `Retry-After`, when the API answered 429. */
  retryAfterSeconds: number | null;
}

export type ApiResult<T> =
  | { ok: true; data: T; error?: never }
  | { ok: false; error: ApiError; data?: never };

export type ListJudgesParams = {
  q?: string;
  court_id?: string;
  active_on?: string;
  status?: JudgeStatus;
  limit?: number;
  offset?: number;
};

export type ListCourtsParams = {
  jurisdiction_id?: string;
  court_type?: string;
  limit?: number;
  offset?: number;
};

export type ListJurisdictionsParams = {
  limit?: number;
  offset?: number;
};

export type ListJudgeCasesParams = {
  filed_from?: string;
  filed_to?: string;
  status?: string;
  case_type?: string;
  limit?: number;
  offset?: number;
};

export type CompareParams = {
  metric: string;
  window?: number;
  court_id?: string;
  jurisdiction_id?: string;
  period_start?: string;
  period_end?: string;
  sort?: "rate" | "numerator" | "denominator" | "value" | "name";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export const client = createClient<paths>({
  baseUrl: API_BASE_URL,
  headers: { Accept: "application/json" },
  // Resolve fetch per call rather than capturing it at import time, so the
  // runtime's patched fetch (Next.js) and test stubs are both honoured.
  fetch: (input: Request) => globalThis.fetch(input),
});

type RawResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  return typeof body.code === "string" && typeof body.message === "string";
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get("retry-after");
  if (header === null) return null;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function toResult<T>(raw: RawResult<T>): ApiResult<T> {
  if (raw.data !== undefined && raw.response.ok) {
    return { ok: true, data: raw.data };
  }
  const status = raw.response.status;
  if (isErrorBody(raw.error)) {
    return {
      ok: false,
      error: {
        status,
        code: raw.error.code,
        message: raw.error.message,
        requestId: raw.error.request_id ?? null,
        retryAfterSeconds: parseRetryAfter(raw.response),
      },
    };
  }
  return {
    ok: false,
    error: {
      status,
      code: "http_error",
      message: `The API answered ${status} ${raw.response.statusText}`.trim(),
      requestId: raw.response.headers.get("x-request-id"),
      retryAfterSeconds: parseRetryAfter(raw.response),
    },
  };
}

function transportFailure(cause: unknown): ApiResult<never> {
  const message = cause instanceof Error ? cause.message : String(cause);
  return {
    ok: false,
    error: {
      status: 0,
      code: "network_error",
      message: `The API at ${API_BASE_URL} could not be reached: ${message}`,
      requestId: null,
      retryAfterSeconds: null,
    },
  };
}

async function call<T>(request: () => Promise<RawResult<T>>): Promise<ApiResult<T>> {
  try {
    return toResult(await request());
  } catch (cause) {
    return transportFailure(cause);
  }
}

/** Drop undefined values so openapi-fetch never serializes `key=undefined`. */
function compact<P extends object>(params: P): P {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined),
  ) as P;
}

export function getJudge(judgeId: string): Promise<ApiResult<JudgeDetail>> {
  return call(() =>
    client.GET("/api/v1/judges/{judge_id}", {
      params: { path: { judge_id: judgeId } },
    }),
  );
}

export function getJudgeService(judgeId: string): Promise<ApiResult<ServiceRecord[]>> {
  return call(() =>
    client.GET("/api/v1/judges/{judge_id}/service", {
      params: { path: { judge_id: judgeId } },
    }),
  );
}

export function listJudges(
  params: ListJudgesParams = {},
): Promise<ApiResult<Page<JudgeSummary>>> {
  return call(() => client.GET("/api/v1/judges", { params: { query: compact(params) } }));
}

export function getCourt(courtId: string): Promise<ApiResult<CourtDetail>> {
  return call(() =>
    client.GET("/api/v1/courts/{court_id}", {
      params: { path: { court_id: courtId } },
    }),
  );
}

export function listCourts(
  params: ListCourtsParams = {},
): Promise<ApiResult<Page<CourtSummary>>> {
  return call(() => client.GET("/api/v1/courts", { params: { query: compact(params) } }));
}

export function getJurisdiction(
  jurisdictionId: string,
): Promise<ApiResult<JurisdictionDetail>> {
  return call(() =>
    client.GET("/api/v1/jurisdictions/{jurisdiction_id}", {
      params: { path: { jurisdiction_id: jurisdictionId } },
    }),
  );
}

export function listJurisdictions(
  params: ListJurisdictionsParams = {},
): Promise<ApiResult<Page<JurisdictionSummary>>> {
  return call(() =>
    client.GET("/api/v1/jurisdictions", { params: { query: compact(params) } }),
  );
}

export function search(q: string, limit = 25): Promise<ApiResult<SearchResponse>> {
  return call(() => client.GET("/api/v1/search", { params: { query: { q, limit } } }));
}

export function getCase(caseId: string): Promise<ApiResult<CaseDetail>> {
  return call(() =>
    client.GET("/api/v1/cases/{case_id}", { params: { path: { case_id: caseId } } }),
  );
}

export function getCaseTimeline(caseId: string): Promise<ApiResult<Timeline>> {
  return call(() =>
    client.GET("/api/v1/cases/{case_id}/timeline", {
      params: { path: { case_id: caseId } },
    }),
  );
}

export function getJudgeCases(
  judgeId: string,
  params: ListJudgeCasesParams = {},
): Promise<ApiResult<Page<CaseSummary>>> {
  return call(() =>
    client.GET("/api/v1/judges/{judge_id}/cases", {
      params: { path: { judge_id: judgeId }, query: compact(params) },
    }),
  );
}

export function getCoverage(): Promise<ApiResult<Coverage>> {
  return call(() => client.GET("/api/v1/coverage"));
}

export function getRegistry(): Promise<ApiResult<Registry>> {
  return call(() => client.GET("/api/v1/metrics"));
}

export function getJudgeMetrics(judgeId: string): Promise<ApiResult<SubjectMetrics>> {
  return call(() =>
    client.GET("/api/v1/judges/{judge_id}/metrics", {
      params: { path: { judge_id: judgeId } },
    }),
  );
}

export function getCourtMetrics(courtId: string): Promise<ApiResult<SubjectMetrics>> {
  return call(() =>
    client.GET("/api/v1/courts/{court_id}/metrics", {
      params: { path: { court_id: courtId } },
    }),
  );
}

export function compareMetrics(params: CompareParams): Promise<ApiResult<ComparePage>> {
  return call(() =>
    client.GET("/api/v1/metrics/compare", { params: { query: compact(params) } }),
  );
}

export function getObservationProvenance(
  observationId: string,
): Promise<ApiResult<ObservationProvenance>> {
  return call(() =>
    client.GET("/api/v1/metrics/{observation_id}/provenance", {
      params: { path: { observation_id: observationId } },
    }),
  );
}

/** The one write path: a correction request; the contact is encrypted by the API. */
export function submitCorrection(body: CorrectionIn): Promise<ApiResult<CorrectionAccepted>> {
  return call(() => client.POST("/api/v1/corrections", { body }));
}
