// web/components/states.tsx
// Empty and error states every fetch renders instead of a blank region. The
// error state shows the API's stable code and request id so a report can be
// matched to the API log; it never shows a stack trace or SQL (the API does
// not send one).
import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";

import type { ApiError } from "@/lib/api/client";

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      role="status"
      data-testid="empty-state"
      className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center"
    >
      <Inbox aria-hidden="true" className="size-6 text-muted-foreground" />
      <p className="font-medium">{title}</p>
      {children ? <div className="text-sm text-muted-foreground">{children}</div> : null}
    </div>
  );
}

function describe(error: ApiError): string {
  switch (error.code) {
    case "network_error":
      return "The API could not be reached. Check that it is running and that NEXT_PUBLIC_API_BASE_URL points at it.";
    case "rate_limited":
      return error.retryAfterSeconds === null
        ? "Too many searches in a short time. Wait a moment and try again."
        : `Too many searches in a short time. Try again in ${error.retryAfterSeconds} seconds.`;
    case "database_unavailable":
      return "The API is up but its database is not reachable right now.";
    case "validation_error":
      return error.message;
    default:
      return error.message;
  }
}

export function ErrorState({ what, error }: { what: string; error: ApiError }) {
  return (
    <div
      role="alert"
      data-testid="error-state"
      className="flex flex-col gap-2 rounded-xl border border-destructive/40 bg-destructive/5 px-6 py-6"
    >
      <p className="flex items-center gap-2 font-medium">
        <AlertTriangle aria-hidden="true" className="size-5 text-destructive" />
        Could not load {what}
      </p>
      <p className="text-sm">{describe(error)}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-xs text-muted-foreground">
        <dt>code</dt>
        <dd>{error.code}</dd>
        <dt>status</dt>
        <dd>{error.status === 0 ? "no response" : error.status}</dd>
        {error.requestId ? (
          <>
            <dt>request id</dt>
            <dd>{error.requestId}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}
