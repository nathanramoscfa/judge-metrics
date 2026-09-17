// web/app/about/page.tsx
// About: what JudgeMetrics is and is not.
import type { Metadata } from "next";
import Link from "next/link";

import { REPOSITORY_URL } from "@/lib/links";

export const metadata: Metadata = { title: "About" };

export default function AboutPage() {
  return (
    <article className="flex max-w-3xl flex-col gap-4">
      <h1 className="text-3xl font-semibold tracking-tight">About</h1>
      <p>
        JudgeMetrics is a transparent, reproducible analytics platform over public
        criminal-court records. It connects judicial assignments, case events,
        dispositions, pretrial decisions, sentences, and documented subsequent
        justice-system events so that judicial outcomes can be measured and compared,
        with every statistic traceable to versioned source records and a published
        methodology.
      </p>
      <p>
        It is not a judge-review site and it does not produce a &ldquo;good judge&rdquo;
        or &ldquo;bad judge&rdquo; score. It reports documented outcomes, comparative
        statistics with their uncertainty, and the coverage and limitations of the data
        behind them. Persons are pseudonymous on every public surface.
      </p>
      <ul className="list-disc space-y-1 pl-6 text-sm">
        <li>
          <Link href="/methodology" className="text-primary hover:underline">
            Methodology
          </Link>
        </li>
        <li>
          <a href={REPOSITORY_URL} className="text-primary hover:underline">
            Source code and roadmap on GitHub
          </a>
        </li>
      </ul>
    </article>
  );
}
