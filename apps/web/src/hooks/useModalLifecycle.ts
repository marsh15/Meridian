"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/* Escape to close, body scroll lock, a short exit animation before the
   caller actually unmounts the modal, and the keyboard behavior
   aria-modal="true" promises: Tab cycles inside the dialog, and focus
   returns to the trigger on close. Attach the returned ref to the
   [role="dialog"] element. */
export function useModalLifecycle(onClose: () => void) {
  const [closing, setClosing] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  const close = useCallback(() => {
    if (closing) return;
    setClosing(true);
    timer.current = setTimeout(onClose, 190);
  }, [closing, onClose]);

  useEffect(() => {
    triggerRef.current = document.activeElement as HTMLElement | null;

    function focusables(): HTMLElement[] {
      const root = dialogRef.current;
      if (!root) return [];
      return [...root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((el) => el.offsetParent !== null || el === document.activeElement);
    }

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
      if (e.key === "Tab" && dialogRef.current) {
        const items = focusables();
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        const inside = dialogRef.current.contains(active);
        if (e.shiftKey && (!inside || active === first)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (!inside || active === last)) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
      triggerRef.current?.focus?.();
    };
  }, []);

  /* clear any pending unmount only on real teardown, never mid-close */
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  return { closing, close, dialogRef };
}
