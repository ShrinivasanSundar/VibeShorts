"use client";

import { useEffect, useState } from "react";
import { useIsFetching } from "@tanstack/react-query";
import { useLoading } from "../lib/loading";
import { Reel } from "./loading-state";

// Waits briefly before appearing so quick operations do not flash a loader.
const DELAY_MS = 300;

export function GlobalLoader() {
  const working = useLoading((s) => s.pending > 0);
  // First loads only: queries with no data yet. Background refreshes stay silent.
  const loading =
    useIsFetching({ predicate: (q) => q.state.status === "pending" }) > 0;
  const pending = working || loading;
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!pending) {
      setVisible(false);
      return;
    }
    const timer = setTimeout(() => setVisible(true), DELAY_MS);
    return () => clearTimeout(timer);
  }, [pending]);
  return (
    <div
      className="global-loader"
      role="status"
      aria-live="polite"
      data-visible={visible}
    >
      {visible && (
        <>
          <Reel className="global-loader-reel" />
          <span>{working ? "Working on it…" : "Loading…"}</span>
        </>
      )}
    </div>
  );
}
