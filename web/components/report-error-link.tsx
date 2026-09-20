// web/components/report-error-link.tsx
// "Report a data error": the link to /corrections prefilled with the
// record it sits beside (a judge, court, or case header, or a metric panel
// with its first observation). The brief's judge profile footer names this
// action; here it is a header action so it is reachable from every surface.
import { Flag } from "lucide-react";
import Link from "next/link";

import { type CorrectionTargetType, correctionHref } from "@/lib/corrections";
import { cn } from "@/lib/utils";

export function ReportErrorLink({
  targetType,
  targetId,
  label,
  className,
}: {
  targetType: CorrectionTargetType;
  targetId: string;
  /** The record's name, carried to the form as `label`. */
  label?: string | null;
  className?: string;
}) {
  return (
    <Link
      href={correctionHref({ type: targetType, id: targetId, label })}
      className={cn(
        "inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline",
        className,
      )}
      data-testid="report-data-error"
      data-target-type={targetType}
      data-target-id={targetId}
    >
      <Flag aria-hidden="true" className="size-3" />
      Report a data error
    </Link>
  );
}
