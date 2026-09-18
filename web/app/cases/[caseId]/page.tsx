// web/app/cases/[caseId]/page.tsx
// A case: the header (court, number, type, status, filed and closed dates,
// the synthetic badge), the timeline, the charges, the judge assignments,
// the attributed decisions with actor badges and pretrial detail, the
// sentence, and the "Sources" panel listing every artifact behind the
// case. Parties are pseudonymous keys: no name exists anywhere in the
// canonical data.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActorBadge, DiscretionBadge, SyntheticBadge } from "@/components/badges";
import { CaseTimeline } from "@/components/case-timeline";
import { ProvenancePanel } from "@/components/provenance-panel";
import { EmptyState, ErrorState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  getCase,
  getCaseTimeline,
  type Decision,
  type PretrialRelease,
  type Sentence,
} from "@/lib/api/client";
import { formatDate, formatDateTime, formatInteger, isUuid, titleCase } from "@/lib/format";

export const dynamic = "force-dynamic";

type Params = Promise<{ caseId: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { caseId } = await params;
  if (!isUuid(caseId)) return { title: "Case" };
  const result = await getCase(caseId);
  return { title: result.ok ? `Case ${result.data.case_number}` : "Case" };
}

function amount(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const number = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(number) ? `$${formatInteger(Math.round(number))}` : String(value);
}

function conditions(release: PretrialRelease): string {
  const names = Object.entries(release.conditions)
    .filter(([, on]) => on)
    .map(([name]) => titleCase(name));
  return names.length ? names.join(", ") : "none recorded";
}

function PretrialDetail({ release }: { release: PretrialRelease }) {
  return (
    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs" data-testid="pretrial-detail">
      <dt className="text-muted-foreground">release type</dt>
      <dd>{titleCase(release.release_type)}</dd>
      <dt className="text-muted-foreground">detained</dt>
      <dd>{release.detained_flag ? "yes" : "no"}</dd>
      <dt className="text-muted-foreground">bond</dt>
      <dd>{amount(release.bond_amount)}</dd>
      <dt className="text-muted-foreground">released</dt>
      <dd>
        {release.release_at ? (
          <time dateTime={release.release_at}>{formatDateTime(release.release_at)}</time>
        ) : (
          "—"
        )}
      </dd>
      <dt className="text-muted-foreground">conditions</dt>
      <dd>{conditions(release)}</dd>
    </dl>
  );
}

function DecisionRow({ decision }: { decision: Decision }) {
  return (
    <li data-testid="decision" data-decision-type={decision.decision_type} className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{titleCase(decision.decision_type)}</span>
        <ActorBadge actor={decision.actor_type} />
        <DiscretionBadge classification={decision.judicial_discretion_classification} />
        <time dateTime={decision.decision_at} className="text-xs text-muted-foreground">
          {formatDateTime(decision.decision_at)}
        </time>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {decision.judge ? (
          <>
            Decided by{" "}
            <Link href={`/judges/${decision.judge.id}`} className="text-primary hover:underline">
              {decision.judge.canonical_name}
            </Link>
          </>
        ) : (
          "No judge attributed"
        )}
        {decision.public_person_key ? (
          <>
            {" · "}subject <span className="font-mono">{decision.public_person_key}</span>
          </>
        ) : null}
      </p>
      {decision.pretrial_release ? <PretrialDetail release={decision.pretrial_release} /> : null}
    </li>
  );
}

function SentenceRow({ sentence }: { sentence: Sentence }) {
  const components = Object.entries(sentence.components)
    .filter(([, on]) => on)
    .map(([name]) => titleCase(name));
  return (
    <li data-testid="sentence" className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Sentence</span>
        <time dateTime={sentence.sentence_at} className="text-xs text-muted-foreground">
          {formatDateTime(sentence.sentence_at)}
        </time>
      </div>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-muted-foreground">incarceration</dt>
        <dd>{sentence.incarceration_days === null ? "—" : `${formatInteger(sentence.incarceration_days)} days`}</dd>
        <dt className="text-muted-foreground">probation</dt>
        <dd>{sentence.probation_days === null ? "—" : `${formatInteger(sentence.probation_days)} days`}</dd>
        <dt className="text-muted-foreground">fine</dt>
        <dd>{amount(sentence.fine_amount)}</dd>
        <dt className="text-muted-foreground">components</dt>
        <dd>{components.length ? components.join(", ") : "—"}</dd>
        <dt className="text-muted-foreground">judge</dt>
        <dd>
          {sentence.judge ? (
            <Link href={`/judges/${sentence.judge.id}`} className="text-primary hover:underline">
              {sentence.judge.canonical_name}
            </Link>
          ) : (
            "not attributed"
          )}
        </dd>
      </dl>
    </li>
  );
}

export default async function CasePage({ params }: { params: Params }) {
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();

  const [result, timeline] = await Promise.all([getCase(caseId), getCaseTimeline(caseId)]);
  if (!result.ok) {
    if (result.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Case</h1>
        <ErrorState what="this case" error={result.error} />
      </div>
    );
  }

  const c = result.data;
  const disposed = c.charges.filter((charge) => charge.disposition && charge.disposition !== "pending");

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          <Link href={`/courts/${c.court.id}`} className="text-primary hover:underline" data-testid="case-court">
            {c.court.canonical_name}
          </Link>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-3xl font-semibold tracking-tight" data-testid="case-number">
            {c.case_number}
          </h1>
          <Badge variant="outline">{titleCase(c.case_type)}</Badge>
          <Badge variant={c.status === "open" ? "default" : "secondary"} data-testid="case-status">
            {titleCase(c.status)}
          </Badge>
          {c.synthetic ? <SyntheticBadge /> : null}
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          <div className="flex gap-1.5">
            <dt>Filed:</dt>
            <dd className="text-foreground">
              {c.filed_date ? <time dateTime={c.filed_date}>{formatDate(c.filed_date)}</time> : "—"}
            </dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Closed:</dt>
            <dd className="text-foreground">
              {c.closed_date ? <time dateTime={c.closed_date}>{formatDate(c.closed_date)}</time> : "open"}
            </dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Parties:</dt>
            <dd className="text-foreground" data-testid="case-parties">
              {c.parties.length === 0
                ? "none on file"
                : c.parties
                    .map((party) => `${titleCase(party.party_type)} ${party.public_person_key ?? "(unresolved)"}`)
                    .join("; ")}
            </dd>
          </div>
        </dl>
        <p className="text-xs text-muted-foreground">
          Persons are pseudonymous: a public key identifies a resolved person across cases and
          never a name. An arrest or charge is not a conviction; each fact below is a separate
          record with its own actor.
        </p>
      </header>

      <section aria-labelledby="timeline-heading" className="flex flex-col gap-3">
        <h2 id="timeline-heading" className="text-lg font-semibold">
          Timeline
        </h2>
        {!timeline.ok ? (
          <ErrorState what="the case timeline" error={timeline.error} />
        ) : timeline.data.entries.length === 0 ? (
          <EmptyState title="No dated fact is on file for this case." />
        ) : (
          <CaseTimeline entries={timeline.data.entries} />
        )}
      </section>

      <section aria-labelledby="charges-heading" className="flex flex-col gap-3">
        <h2 id="charges-heading" className="text-lg font-semibold">
          Charges
        </h2>
        {c.charges.length === 0 ? (
          <EmptyState title="No charge is on file for this case." />
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <Table data-testid="charges-table">
              <caption className="sr-only">Charges in case {c.case_number}</caption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Statute</TableHead>
                  <TableHead scope="col">Description</TableHead>
                  <TableHead scope="col">Category</TableHead>
                  <TableHead scope="col">Severity</TableHead>
                  <TableHead scope="col">Violent</TableHead>
                  <TableHead scope="col">Filed</TableHead>
                  <TableHead scope="col">Disposition</TableHead>
                  <TableHead scope="col">Disposed by</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {c.charges.map((charge, index) => (
                  <TableRow key={`${charge.statute_code ?? "charge"}:${index}`} data-testid="charge-row">
                    <TableCell className="font-mono text-xs">{charge.statute_code ?? "—"}</TableCell>
                    <TableCell>{charge.description}</TableCell>
                    <TableCell>{titleCase(charge.offense_category)}</TableCell>
                    <TableCell>{titleCase(charge.severity)}</TableCell>
                    <TableCell>{charge.violent_flag === null ? "—" : charge.violent_flag ? "yes" : "no"}</TableCell>
                    <TableCell>
                      <time dateTime={charge.filed_at}>{formatDate(charge.filed_at)}</time>
                    </TableCell>
                    <TableCell>
                      {charge.disposition ? titleCase(charge.disposition) : "—"}
                      {charge.disposed_at ? (
                        <span className="block text-xs text-muted-foreground">
                          <time dateTime={charge.disposed_at}>{formatDate(charge.disposed_at)}</time>
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell>{charge.disposition_actor ? <ActorBadge actor={charge.disposition_actor} /> : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <div className="grid gap-8 lg:grid-cols-2">
        <section aria-labelledby="assignments-heading" className="flex flex-col gap-3">
          <h2 id="assignments-heading" className="text-lg font-semibold">
            Judge assignments
          </h2>
          {c.assignments.length === 0 ? (
            <EmptyState title="No judge assignment is on file." />
          ) : (
            <ul className="flex flex-col gap-2" data-testid="assignments">
              {c.assignments.map((assignment, index) => (
                <li key={`${assignment.judge.id}:${index}`} data-testid="assignment" className="rounded-lg border p-3 text-sm">
                  <Link href={`/judges/${assignment.judge.id}`} className="font-medium text-primary hover:underline">
                    {assignment.judge.canonical_name}
                  </Link>{" "}
                  <span className="text-muted-foreground">({titleCase(assignment.assignment_type)})</span>
                  <p className="text-xs text-muted-foreground">
                    <time dateTime={assignment.start_at}>{formatDateTime(assignment.start_at)}</time>
                    {" – "}
                    {assignment.end_at ? (
                      <time dateTime={assignment.end_at}>{formatDateTime(assignment.end_at)}</time>
                    ) : (
                      "current"
                    )}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="disposition-heading" className="flex flex-col gap-3">
          <h2 id="disposition-heading" className="text-lg font-semibold">
            Disposition
          </h2>
          {disposed.length === 0 ? (
            <EmptyState title="No charge has been disposed of." />
          ) : (
            <ul className="flex flex-col gap-2 text-sm" data-testid="disposition">
              {disposed.map((charge, index) => (
                <li key={`${charge.statute_code ?? "charge"}:${index}`} className="flex flex-wrap items-center gap-2">
                  <span>
                    {titleCase(charge.disposition ?? "")}: {charge.description}
                  </span>
                  {charge.disposition_actor ? <ActorBadge actor={charge.disposition_actor} /> : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section aria-labelledby="decisions-heading" className="flex flex-col gap-3">
        <h2 id="decisions-heading" className="text-lg font-semibold">
          Attributed decisions
        </h2>
        <p className="text-sm text-muted-foreground">
          Each decision names who made it. Only judicial decisions enter judge-level metrics; a
          prosecutor&apos;s dismissal or a statutory release is never counted as a judge&apos;s.
        </p>
        {c.decisions.length === 0 ? (
          <EmptyState title="No decision is on file for this case." />
        ) : (
          <ul className="flex flex-col gap-2" data-testid="decisions">
            {c.decisions.map((decision, index) => (
              <DecisionRow key={`${decision.decision_type}:${decision.decision_at}:${index}`} decision={decision} />
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <section aria-labelledby="sentence-heading" className="flex flex-col gap-3">
          <h2 id="sentence-heading" className="text-lg font-semibold">
            Sentence
          </h2>
          {c.sentences.length === 0 ? (
            <EmptyState title="No sentence is on file for this case." />
          ) : (
            <ul className="flex flex-col gap-2" data-testid="sentences">
              {c.sentences.map((sentence, index) => (
                <SentenceRow key={`${sentence.sentence_at}:${index}`} sentence={sentence} />
              ))}
            </ul>
          )}
        </section>
        <ProvenancePanel
          title="Sources"
          description="Every raw artifact behind this case and the rows it contains. Each sha256 names the exact bytes kept in the immutable raw lake."
          entries={c.provenance}
          issueTitle={`Case ${c.case_number} (case ${c.id})`}
        />
      </div>
    </article>
  );
}
