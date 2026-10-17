"use client";

import { useEffect, useRef } from "react";
import { useConfirm } from "../lib/confirm";

export function ConfirmDialog() {
  const request = useConfirm((s) => s.request);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!request) return;
    const previous = document.activeElement as HTMLElement | null;
    // Focus Cancel first so a stray Enter never confirms a permanent delete.
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => previous?.focus();
  }, [request]);
  if (!request) return null;
  return (
    <div
      className="chat-dialog-backdrop confirm-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) request.resolve(false);
      }}
    >
      <div
        ref={ref}
        className="chat-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-message"
        onKeyDown={(e) => {
          if (e.key === "Escape") request.resolve(false);
          if (e.key === "Tab") {
            const buttons =
              ref.current?.querySelectorAll<HTMLButtonElement>("button");
            if (!buttons?.length) return;
            const first = buttons[0],
              last = buttons[buttons.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <h2 id="confirm-title">{request.title}</h2>
        <p id="confirm-message">{request.message}</p>
        <div>
          <button onClick={() => request.resolve(false)}>Cancel</button>
          <button className="confirm-danger" onClick={() => request.resolve(true)}>
            {request.confirmLabel || "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
