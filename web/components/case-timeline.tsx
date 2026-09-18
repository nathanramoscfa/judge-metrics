// web/components/case-timeline.tsx
// A case's timeline as an ordered list: one item per dated fact, with a
// <time> element, the kind, the actor badge when the source records who
// acted, the judge when one is named, the label, and the artifact the row
// came from. Date-only facts (filed, closed) render as dates; timestamped
// facts render with their time.
import Link from "next/link";

import { ActorBadge, DiscretionBadge } from "@/components/badges";
import type { TimelineEntry, TimelineKind } from "@/lib/api/client";
import { formatDate, formatDateTime, truncateHash } from "@/lib/format";

export const KIND_LABELS: Record<TimelineKind, string> = {
  filed: "Filed",
  assignment_start: "Assignment",
  assignment_end: "Assignment ended",
  event: "Event",
  decision: "Decision",
  charge_filed: "Charge filed",
  charge_disposed: "Charge disposed",
  sentence: "Sentence",
  closed: "Closed",
};

const DATE_ONLY: ReadonlySet<TimelineKind> = new Set<TimelineKind>(["filed", "closed"]);

function entryDate(entry: TimelineEntry): string {
  const date = entry.detail.date;
  if (DATE_ONLY.has(entry.kind) && typeof date === "string") return date;
  return entry.at;
}

function discretion(entry: TimelineEntry): string | null {
  const value = entry.detail.judicial_discretion_classification;
  return entry.kind === "decision" && typeof value === "string" ? value : null;
}

export function TimelineItem({ entry }: { entry: TimelineEntry }) {
  const when = entryDate(entry);
  const dateOnly = DATE_ONLY.has(entry.kind);
  const classification = discretion(entry);
  return (
    <li
      data-testid="timeline-entry"
      data-kind={entry.kind}
      className="grid gap-x-4 gap-y-1 border-l-2 border-border py-2 pl-4 sm:grid-cols-[11rem_1fr]"
    >
      <time dateTime={when} className="text-sm tabular-nums text-muted-foreground">
        {dateOnly ? formatDate(when) : formatDateTime(when)}
      </time>
      <div className="flex flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {KIND_LABELS[entry.kind]}
          </span>
          {entry.actor_type ? <ActorBadge actor={entry.actor_type} /> : null}
          {classification ? <DiscretionBadge classification={classification} /> : null}
        </p>
        <p className="font-medium">{entry.label}</p>
        <p className="text-xs text-muted-foreground">
          {entry.judge ? (
            <>
              Judge{" "}
              <Link href={`/judges/${entry.judge.id}`} className="text-primary hover:underline">
                {entry.judge.canonical_name}
              </Link>
              {" · "}
            </>
          ) : null}
          Source{" "}
          <span className="font-mono" data-testid="timeline-source">
            {entry.source.external_record_id ?? entry.source.source}
          </span>{" "}
          <span className="font-mono" aria-label={`sha256 ${entry.source.raw_sha256}`}>
            {truncateHash(entry.source.raw_sha256)}
          </span>
        </p>
      </div>
    </li>
  );
}

export function CaseTimeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <ol data-testid="case-timeline" className="flex flex-col">
      {entries.map((entry, index) => (
        <TimelineItem key={`${entry.kind}:${entry.at}:${index}`} entry={entry} />
      ))}
    </ol>
  );
}
