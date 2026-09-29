import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge class names, resolving Tailwind conflicts. Used by every ui/ primitive. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
