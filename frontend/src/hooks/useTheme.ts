"use client";

import { useState, useEffect, useCallback } from "react";

/**
 * Manages light / dark theme state, persisted to localStorage
 * and applied via `data-theme` attribute + `.dark` class.
 */
export function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  // Hydrate from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("vibeshorts_theme") as "light" | "dark" | null;
    const initial = saved || "light";
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
    document.documentElement.classList.toggle("dark", initial === "dark");
  }, []);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      localStorage.setItem("vibeshorts_theme", next);
      return next;
    });
  }, []);

  return { theme, toggleTheme: toggle } as const;
}
