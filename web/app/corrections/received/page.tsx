// web/app/corrections/received/page.tsx
// /corrections/received?id=…: the acknowledgement after a correction request
// is accepted. It shows the request id and what happens next, and nothing
// the requester submitted — the contact never reaches this page (the route
// handler returns the id and the status only).
import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState } from "@/components/states";
import { isUuid } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Correction request received" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function CorrectionReceivedPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const raw = Array.isArray(query.id) ? query.id[0] : query.id;
  const id = raw && isUuid(raw) ? raw : null;
  return (
    <article className="flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Correction request received</h1>
        <p className="text-muted-foreground">Thank you. The request is stored and queued for review.</p>
      </header>
      {id ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-xl border bg-muted/30 p-4 text-sm" data-testid="received">
          <dt className="text-muted-foreground">Request id</dt>
          <dd className="font-mono" data-testid="correction-id">
            {id}
          </dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd data-testid="correction-status">received</dd>
        </dl>
      ) : (
        <EmptyState title="No request id was given.">
          The address should carry the id the form received; if you reached this page another
          way, nothing was lost — a submitted request is stored before this page is shown.
        </EmptyState>
      )}
      <section aria-labelledby="next-heading" className="flex flex-col gap-2 text-sm">
        <h2 id="next-heading" className="text-lg font-semibold">
          What happens next
        </h2>
        <ol className="list-decimal space-y-1 pl-5">
          <li>A reviewer compares the record with the raw source artifact it cites and with any material you linked.</li>
          <li>A demonstrably wrong or legally restricted record is corrected or withheld from every public surface, and every published number it entered is recomputed.</li>
          <li>The change is written to the append-only audit log; the raw artifact is never altered.</li>
          <li>You hear back at the contact you gave, which is stored encrypted and used for nothing else. Quote the request id above.</li>
        </ol>
      </section>
      <p className="text-sm">
        <Link href="/" className="text-primary hover:underline">
          Back to the home page
        </Link>
        {" · "}
        <Link href="/methodology" className="text-primary hover:underline">
          Methodology
        </Link>
      </p>
    </article>
  );
}
