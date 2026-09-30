import { useEffect } from "react";
import { usePlayheadStore } from "../store/playhead";
import { isTypingTarget } from "@/lib/utils";

/**
 * Global review-workspace shortcuts (docs/04-FRONTEND.md §5.1): J/K/L shuttle, arrow-key frame
 * stepping, Shift+arrow one-second stepping, `G` focuses the "go to timecode" toolbar input.
 * Ignored while the focus is inside a text field so typing case notes etc. elsewhere still works.
 */
export function useReviewShortcuts(goToInputRef: React.RefObject<HTMLInputElement | null>) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return;
      const store = usePlayheadStore.getState();
      switch (e.key) {
        case "j":
        case "J":
          e.preventDefault();
          store.cycleShuttle(-1);
          break;
        case "k":
        case "K":
          e.preventDefault();
          store.cycleShuttle(0);
          break;
        case "l":
        case "L":
          e.preventDefault();
          store.cycleShuttle(1);
          break;
        case " ":
          e.preventDefault();
          if (store.playing) store.cycleShuttle(0);
          else store.cycleShuttle(1);
          break;
        case "ArrowLeft":
          e.preventDefault();
          store.setPlaying(false);
          if (e.shiftKey) store.stepSeconds(-1);
          else store.stepFrame(-1);
          break;
        case "ArrowRight":
          e.preventDefault();
          store.setPlaying(false);
          if (e.shiftKey) store.stepSeconds(1);
          else store.stepFrame(1);
          break;
        case "g":
        case "G":
          e.preventDefault();
          goToInputRef.current?.focus();
          goToInputRef.current?.select();
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goToInputRef]);
}
