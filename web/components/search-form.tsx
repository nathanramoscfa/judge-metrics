// web/components/search-form.tsx
// The global search box: a plain GET form to /search?q= so it works without
// JavaScript, plus the `/` keyboard shortcut that focuses the input when the
// viewer is not already typing somewhere else.
"use client";

import { SearchIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const EDITABLE_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return EDITABLE_TAGS.has(target.tagName) || target.isContentEditable;
}

export function SearchForm({
  defaultValue = "",
  size = "default",
  autoFocus = false,
  className,
}: {
  defaultValue?: string;
  size?: "default" | "large";
  autoFocus?: boolean;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const large = size === "large";

  return (
    <form
      action="/search"
      method="get"
      role="search"
      aria-label="Search judges and courts"
      className={cn("flex w-full items-center gap-2", className)}
    >
      <label htmlFor="global-search" className="sr-only">
        Search judges and courts by name
      </label>
      <Input
        ref={inputRef}
        id="global-search"
        name="q"
        type="search"
        placeholder="Search judge or court by name…"
        defaultValue={defaultValue}
        autoComplete="off"
        autoFocus={autoFocus}
        minLength={1}
        maxLength={200}
        required
        data-testid="search-input"
        className={cn(large && "h-11 text-base md:text-base")}
      />
      <Button type="submit" size={large ? "lg" : "default"} aria-label="Search">
        <SearchIcon aria-hidden="true" />
        <span className={cn(!large && "sr-only")}>Search</span>
      </Button>
      <kbd
        aria-hidden="true"
        className="hidden rounded border px-1.5 py-0.5 font-mono text-xs text-muted-foreground md:inline-block"
        title="Press / to focus search"
      >
        /
      </kbd>
    </form>
  );
}
