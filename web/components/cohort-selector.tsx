// web/components/cohort-selector.tsx
// The comparison-cohort selector on the judge page: "Same court, same
// period" (the default) or "Jurisdiction, same period". The choice is the
// `cohort=court|jurisdiction` query parameter the server page reads; the
// window selector beside it is the `window=` parameter. Both are plain GET
// forms through QuerySelect, so they work without JavaScript.
"use client";

import { QuerySelect } from "@/components/query-select";
import { COHORTS, type CohortKind } from "@/lib/metrics";

export function CohortSelector({
  value,
  action,
  keep,
}: {
  value: CohortKind;
  /** The judge page path, with the section fragment to return to. */
  action: string;
  keep?: Record<string, string | undefined>;
}) {
  return (
    <QuerySelect
      name="cohort"
      value={value}
      action={action}
      keep={keep}
      label="Comparison cohort"
      testId="cohort-selector"
      options={(Object.keys(COHORTS) as CohortKind[]).map((kind) => ({
        value: kind,
        label: COHORTS[kind],
      }))}
    />
  );
}

export function WindowSelector({
  value,
  windows,
  action,
  keep,
}: {
  value: number;
  /** The registry's windows, in days. */
  windows: number[];
  action: string;
  keep?: Record<string, string | undefined>;
}) {
  return (
    <QuerySelect
      name="window"
      value={String(value)}
      action={action}
      keep={keep}
      label="Follow-up window"
      testId="window-selector"
      options={windows.map((days) => ({ value: String(days), label: `${days} days` }))}
    />
  );
}
