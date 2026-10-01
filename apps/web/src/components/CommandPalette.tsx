"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useModalLifecycle } from "@/hooks/useModalLifecycle";
import type { MarketCardData } from "@meridian/contracts";

const OPEN_EVENT = "meridian:open-palette";
const LIST_ID = "palette-list";
const MAX_MARKET_RESULTS = 8;

interface PaletteItem {
  id: string;
  kind: "command" | "market";
  label: string;
  right: string;
  priceClass?: boolean;
  ticker?: string;
  path?: string;
  action?: "sign-in" | "sign-out";
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10 10l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/* fuzzy-ish ranking: question prefix beats word-start beats substring beats
   ticker/category-only; ties break on volume */
function rank(m: MarketCardData, q: string): number {
  if (!q) return 0;
  const question = m.question.toLowerCase();
  if (question.startsWith(q)) return 0;
  if (question.includes(` ${q}`)) return 1;
  if (question.includes(q)) return 2;
  return 3;
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false);

  /* ⌘K from anywhere — but never stack on a dialog that already owns the screen */
  useHotkeys({
    "mod+k": () => {
      if (document.querySelector('[role="dialog"]')) return;
      setOpen(true);
    },
  });

  /* the Header's Search button dispatches this */
  useEffect(() => {
    function onOpen() {
      setOpen(true);
    }
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  if (!open) return null;
  return <PaletteBody onClose={() => setOpen(false)} />;
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { user, logout, openAuth } = useAuth();
  const { closing, close, dialogRef } = useModalLifecycle(onClose);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  /* same cache key as the home grid — opening the palette refreshes prices */
  const { data, isLoading } = useQuery({ queryKey: ["markets"], queryFn: api.markets });
  const markets = data?.markets;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setActive(0);
  }, [query]);

  const items: PaletteItem[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    const tokens = q ? q.split(/\s+/) : [];

    /* the create-market modal is local state on the home page, so "New market"
       routes there rather than dispatching an event nobody listens for */
    const commands: PaletteItem[] = [
      { id: "cmd-portfolio", kind: "command", label: "Portfolio", right: "Page", path: "/portfolio" },
      { id: "cmd-leaderboard", kind: "command", label: "Leaderboard", right: "Page", path: "/leaderboard" },
      { id: "cmd-categories", kind: "command", label: "Categories", right: "Page", path: "/categories" },
      { id: "cmd-new-market", kind: "command", label: "New market", right: "Page", path: "/" },
      user
        ? { id: "cmd-sign-out", kind: "command", label: "Sign out", right: "Account", action: "sign-out" }
        : { id: "cmd-sign-in", kind: "command", label: "Sign in", right: "Account", action: "sign-in" },
    ];

    const matched: PaletteItem[] = commands.filter((c) => {
      const hay = c.label.toLowerCase();
      return !tokens.length || tokens.every((t) => hay.includes(t));
    });

    if (markets) {
      const hits = markets
        .filter((m) => {
          if (!tokens.length) return true;
          const hay = `${m.question} ${m.ticker} ${m.category}`.toLowerCase();
          return tokens.every((t) => hay.includes(t));
        })
        .map((m) => ({ m, score: rank(m, q) }))
        .sort((a, b) => a.score - b.score || b.m.volumeCents - a.m.volumeCents)
        .slice(0, MAX_MARKET_RESULTS);

      for (const { m } of hits) {
        const resolved = m.status === "resolved";
        matched.push({
          id: `mkt-${m.id}`,
          kind: "market",
          label: m.question,
          ticker: m.ticker,
          right: resolved ? `Resolved ${m.outcome === "yes" ? "YES" : "NO"}` : `${m.price}¢`,
          priceClass: !resolved,
          path: `/market/${m.slug}`,
        });
      }
    }

    return matched;
  }, [markets, query, user]);

  /* data arriving late can shrink the list — clamp the cursor, never let it
    dangle past the end */
  const idx = Math.min(active, Math.max(0, items.length - 1));

  /* keep the highlighted row in view while arrowing through */
  useEffect(() => {
    if (idx >= items.length) return;
    listRef.current?.children[idx]?.scrollIntoView({ block: "nearest" });
  }, [idx, items.length]);

  function runItem(it: PaletteItem) {
    close();
    if (it.action === "sign-out") logout().catch(() => {});
    else if (it.action === "sign-in") openAuth("login");
    else if (it.path) router.push(it.path);
  }

  function onInputKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const max = items.length - 1;
      if (max < 0) return;
      setActive((i) => (e.key === "ArrowDown" ? Math.min(i + 1, max) : Math.max(i - 1, 0)));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(Math.max(0, items.length - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const it = items[idx];
      if (it) runItem(it);
    }
    /* Escape bubbles to the window listener useModalLifecycle owns */
  }

  return (
    <div
      className={`modal-overlay palette-overlay ${closing ? "closing" : ""}`}
      onClick={close}
    >
      <div
        className="modal card palette"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        ref={dialogRef}
      >
        <div className="palette-input-row">
          <SearchIcon />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            role="combobox"
            aria-expanded="true"
            aria-controls={LIST_ID}
            aria-activedescendant={items.length ? items[idx].id : undefined}
            aria-autocomplete="list"
            aria-label="Search markets and commands"
            placeholder='Search markets — or jump to Portfolio, Leaderboard…'
            autoComplete="off"
            spellCheck={false}
          />
          <span className="palette-kbd" aria-hidden="true">
            esc
          </span>
        </div>

        <div className="palette-list" id={LIST_ID} role="listbox" aria-label="Results" ref={listRef}>
          {items.map((it, i) => (
            <div
              key={it.id}
              id={it.id}
              role="option"
              aria-selected={i === idx}
              className={`palette-item ${it.kind} ${i === idx ? "active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => runItem(it)}
            >
              {it.kind === "market" ? (
                <span className="palette-ticker">{it.ticker}</span>
              ) : (
                <span className="palette-glyph" aria-hidden="true">
                  →
                </span>
              )}
              <span className="palette-label">{it.label}</span>
              <span className={`palette-right ${it.priceClass ? "price" : ""}`}>{it.right}</span>
            </div>
          ))}

          {isLoading && !markets && (
            <div className="palette-skel" aria-hidden="true">
              <div className="skel" />
              <div className="skel" />
              <div className="skel" />
            </div>
          )}

          {!isLoading && items.length === 0 && (
            <div className="palette-empty">
              No matches for <b>“{query.trim()}”</b> — try a ticker or category.
            </div>
          )}
        </div>

        <div className="palette-foot" aria-hidden="true">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> navigate
          </span>
          <span>
            <kbd>↵</kbd> open
          </span>
          <span>
            <kbd>esc</kbd> close
          </span>
          <span className="palette-foot-spacer" />
          <span>Prices in cents</span>
        </div>
      </div>
    </div>
  );
}
