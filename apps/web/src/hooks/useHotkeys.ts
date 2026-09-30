"use client";

import { useEffect, useRef } from "react";

/* ⌘ is "mod" on Apple platforms, Ctrl everywhere else */
export function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /mac/i.test(navigator.platform || navigator.userAgent);
}

/* The typing guard every hotkey surface shares: keys aimed at form fields
   are the field's, not ours — except Escape (always allowed through, so
   modals can close even from inside an input) and mod combos like ⌘K,
   which never insert text. Same bail-out the home page's "/" handler uses. */
export function isTypingGuard(e: KeyboardEvent): boolean {
  if (e.key === "Escape") return false;
  if (isMacPlatform() ? e.metaKey : e.ctrlKey) return false;
  const el = e.target;
  if (!(el instanceof HTMLElement)) return false;
  return (
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.isContentEditable
  );
}

/* "mod+k", "/", "b", "shift+s", "escape" — e.key lowercased, with the
   platform modifier normalized to "mod" */
function comboFor(e: KeyboardEvent): string {
  const key = e.key.toLowerCase();
  const parts: string[] = [];
  if (isMacPlatform() ? e.metaKey : e.ctrlKey) parts.push("mod");
  if (e.shiftKey && key.length === 1) parts.push("shift");
  parts.push(key);
  return parts.join("+");
}

export function useHotkeys(
  map: Record<string, (e: KeyboardEvent) => void>,
  enabled = true,
) {
  /* keep the listener attached once; swap the map as renders refresh it */
  const mapRef = useRef(map);
  useEffect(() => {
    mapRef.current = map;
  }, [map]);

  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      if (isTypingGuard(e)) return;
      const handler = mapRef.current[comboFor(e)];
      if (handler) {
        e.preventDefault();
        handler(e);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
