// web/components/badges.tsx
// Small labelled markers: a judge's status, a search result's entity type,
// and a court's type. Colours carry no judgement — a status is a fact from
// the source, not a rating.
import { Badge } from "@/components/ui/badge";
import type { JudgeStatus, SearchResult } from "@/lib/api/client";
import { titleCase } from "@/lib/format";

const STATUS_VARIANT: Record<JudgeStatus, "default" | "secondary" | "outline"> = {
  active: "default",
  senior: "secondary",
  deceased: "outline",
  retired: "outline",
  resigned: "outline",
  removed: "outline",
  inactive: "outline",
  unknown: "outline",
};

export function StatusBadge({ status }: { status: JudgeStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} data-testid="judge-status">
      {titleCase(status)}
    </Badge>
  );
}

export function EntityTypeBadge({ type }: { type: SearchResult["entity_type"] }) {
  return (
    <Badge variant={type === "judge" ? "default" : "secondary"} data-testid="entity-type">
      {titleCase(type)}
    </Badge>
  );
}

export function CourtTypeBadge({ type }: { type: string }) {
  return <Badge variant="outline">{titleCase(type)}</Badge>;
}
