"use client";

import { useState, useEffect } from "react";
import { checkBackendHealth } from "@/lib/api";

const POLL_INTERVAL_MS = 15_000;

/**
 * Polls the backend health endpoint and returns the current status.
 */
export function useBackendHealth() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    // Initial check
    checkBackendHealth().then(setOnline);

    const id = setInterval(() => {
      checkBackendHealth().then(setOnline);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(id);
  }, []);

  return online;
}
