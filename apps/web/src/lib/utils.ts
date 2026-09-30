import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge class names, resolving Tailwind conflicts. Used by every ui/ primitive. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * True while a keyboard event's target is a text-entry field (or contenteditable) — every global
 * single-key shortcut in the app (review's J/K/L/arrows/G, the `?` shortcut sheet) checks this
 * first so typing "g" into a note or a search box never fires a shortcut instead.
 */
export function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
}
