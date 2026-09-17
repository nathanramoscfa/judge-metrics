// web/components/site-footer.tsx
// The contentinfo landmark: the standing links every page carries.
import Link from "next/link";

import { DATA_SOURCES_URL, REPOSITORY_URL } from "@/lib/links";

export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
        <p>
          Public judicial records, measured transparently. Associations in these
          records are not causes.
        </p>
        <nav aria-label="Footer">
          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <li>
              <a href={DATA_SOURCES_URL} className="hover:text-foreground hover:underline">
                Data sources
              </a>
            </li>
            <li>
              <Link href="/methodology" className="hover:text-foreground hover:underline">
                Methodology
              </Link>
            </li>
            <li>
              <a href={REPOSITORY_URL} className="hover:text-foreground hover:underline">
                Source code
              </a>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
