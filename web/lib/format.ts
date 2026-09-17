// web/lib/format.ts
// Presentation helpers shared by the pages and components. Dates from the
// API are ISO 8601 (`YYYY-MM-DD` or a UTC timestamp) and are rendered in
// UTC so a service date never shifts by a day with the viewer's zone.
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

const integerFormatter = new Intl.NumberFormat("en-US");

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** "Aug 6, 2009" for "2009-08-06"; the input echoed back when it is not a date. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(ISO_DATE.test(value) ? `${value}T00:00:00Z` : value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

/** "Sep 16, 2026, 11:46 PM UTC" for an API timestamp. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateTimeFormatter.format(date);
}

export function formatInteger(value: number): string {
  return integerFormatter.format(value);
}

/** The first `length` hex characters of a digest, followed by an ellipsis. */
export function truncateHash(hash: string, length = 12): string {
  return hash.length <= length ? hash : `${hash.slice(0, length)}…`;
}

/** "district" → "District"; "court_type" → "Court Type". */
export function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** The current UTC date as `YYYY-MM-DD`, the shape `active_on` accepts. */
export function todayIsoDate(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** RFC 4122 shape check so a malformed path id becomes a 404, not an API call. */
export function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

/** `YYYY-MM-DD` shape and calendar check for the court page's `active_on` query. */
export function isIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}
