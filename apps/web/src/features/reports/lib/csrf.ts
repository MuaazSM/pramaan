/**
 * Real-mode mutating routes require the double-submit CSRF header (docs/02-BACKEND.md §11):
 * `POST /auth/login` sets a JS-readable `pramaan_csrf` cookie which must be echoed back in
 * `X-CSRF-Token`. The shared api client does not add it (stub mode does not enforce it), so the
 * reports screen's two POSTs add it themselves. Returns `{}` when the cookie is absent (mock mode,
 * stub mode) so callers can always spread the result into `headers`.
 */
export function csrfHeaders(): Record<string, string> {
  const cookie = typeof document !== "undefined" ? document.cookie : "";
  const match = /(?:^|;\s*)pramaan_csrf=([^;]+)/.exec(cookie);
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}
