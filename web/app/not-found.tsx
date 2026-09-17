// web/app/not-found.tsx
// The 404 page: a malformed or unknown judge or court id lands here.
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">Not found</h1>
      <p className="text-muted-foreground">
        There is no page at this address. The judge or court may not be in the ingested
        sources.
      </p>
      <Link href="/search" className="text-primary hover:underline">
        Search judges and courts
      </Link>
    </div>
  );
}
