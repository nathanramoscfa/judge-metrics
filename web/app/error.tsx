// web/app/error.tsx
// The route error boundary for anything a page did not handle itself. It
// shows the error digest (never the message, which could carry internals)
// and offers a retry.
"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">Something went wrong</h1>
      <p className="text-muted-foreground">This page could not be rendered.</p>
      {error.digest ? (
        <p className="font-mono text-xs text-muted-foreground">digest {error.digest}</p>
      ) : null}
      <Button type="button" variant="outline" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
