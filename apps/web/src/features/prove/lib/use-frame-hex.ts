import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";

/**
 * `GET /frames/{fid}/hex` (before/after byte window around the payload — apps/api/openapi.json's
 * `HexView`). Shared by the prove-it screen (full window, adjustable) and the frame inspector
 * (small default window, just enough to show/verify the payload hash) — same query key shape so
 * navigating from the inspector's "Prove it" link to the prove-it screen for the same frame at
 * the default window reuses the cache instead of re-fetching.
 */
export function useFrameHex(frameId: string | undefined, before = 256, after = 512) {
  return useQuery({
    queryKey: ["frame-hex", frameId, before, after],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/frames/{fid}/hex", {
        params: { path: { fid: frameId! }, query: { before, after } },
      });
      if (error) throw errorFromResponse(response, "the byte window could not be loaded");
      return data ?? null;
    },
    enabled: Boolean(frameId),
    // Widening the before/after window (the prove-it screen's steppers) re-keys the query;
    // keep showing the previous window's bytes while the new one loads instead of flashing a
    // skeleton over an already-rendered grid.
    placeholderData: keepPreviousData,
  });
}
