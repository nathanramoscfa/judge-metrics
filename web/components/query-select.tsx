// web/components/query-select.tsx
// A select bound to one query parameter: a plain GET form that keeps the
// other parameters as hidden inputs, so it works without JavaScript (the
// Apply button submits) and, with JavaScript, submits itself on change. The
// page state stays in the URL, which is what the server page reads.
"use client";

import type { ChangeEvent } from "react";

import { Button } from "@/components/ui/button";

export interface QueryOption {
  value: string;
  label: string;
}

export function QuerySelect({
  name,
  value,
  options,
  keep = {},
  action,
  label,
  testId,
}: {
  name: string;
  value: string;
  options: readonly QueryOption[];
  /** Other query parameters to carry along. */
  keep?: Record<string, string | undefined>;
  /** The page (and optional fragment) the form navigates to. */
  action: string;
  label: string;
  testId?: string;
}) {
  function submitOnChange(event: ChangeEvent<HTMLSelectElement>) {
    event.currentTarget.form?.requestSubmit();
  }
  const id = `${name}-select`;
  return (
    <form method="get" action={action} className="flex items-center gap-2" data-testid={testId}>
      {Object.entries(keep)
        .filter(([key, kept]) => key !== name && kept)
        .map(([key, kept]) => (
          <input key={key} type="hidden" name={key} value={kept} />
        ))}
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <select
        id={id}
        name={name}
        defaultValue={value}
        onChange={submitOnChange}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Button type="submit" variant="outline" size="xs">
        Apply
      </Button>
    </form>
  );
}
