// web/lib/utils.ts
// Class-name merging for the shadcn/ui components: clsx for conditionals,
// tailwind-merge so a caller's utility wins over a component default.
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
