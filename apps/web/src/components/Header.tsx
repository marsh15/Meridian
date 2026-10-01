"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { fmtMoney } from "@/lib/format";
import { AnimatedNumber } from "@/components/AnimatedPrice";
import { isMacPlatform } from "@/hooks/useHotkeys";

function SearchIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10 10l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function ResetIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 12a9 9 0 1 0 2.64-6.36L3 8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M3 3v5h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Header() {
  const { user, ready, logout, resetAccount, openAuth } = useAuth();
  const pathname = usePathname();
  const [armed, setArmed] = useState(false);
  const armTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /* the ⌘/Ctrl hint differs per platform — decide after mount so server and
     first client render agree */
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  /* reset wipes the balance and positions — arm first, then confirm */
  function onReset() {
    if (!armed) {
      setArmed(true);
      if (armTimer.current) clearTimeout(armTimer.current);
      armTimer.current = setTimeout(() => setArmed(false), 3000);
      return;
    }
    setArmed(false);
    resetAccount().catch(() => {});
  }

  return (
    <header className="site-header">
      <div className="wrap header-inner">
        <Link href="/" className="logo" aria-label="Meridian home">
          <span className="logo-mark" aria-hidden="true">
            <svg viewBox="0 0 14 14" fill="none">
              <path d="M1 7L7 1l6 6-6 6z" fill="currentColor" />
            </svg>
          </span>
          <span className="logo-word">Meridian</span>
        </Link>

        <nav className="header-nav">
          <Link href="/" aria-current={pathname === "/" ? "page" : undefined}>
            Markets
          </Link>
          <Link href="/leaderboard" aria-current={pathname === "/leaderboard" ? "page" : undefined}>
            Leaderboard
          </Link>
          <Link href="/categories" aria-current={pathname === "/categories" ? "page" : undefined}>
            Categories
          </Link>
          <Link href="/portfolio" aria-current={pathname === "/portfolio" ? "page" : undefined}>
            Portfolio
          </Link>
        </nav>

        <div className="header-spacer" />

        <button
          className="btn-ghost search-trigger"
          aria-label="Search (Command K)"
          onClick={() => window.dispatchEvent(new Event("meridian:open-palette"))}
        >
          <SearchIcon />
          <span className="search-trigger-label">Search</span>
          <kbd className="palette-kbd" aria-hidden="true">
            {mounted && !isMacPlatform() ? "Ctrl K" : "⌘K"}
          </kbd>
        </button>

        {ready && user && (
          <div className="user-chip" title={`Signed in as ${user.email}`}>
            <span className="user-avatar" aria-hidden="true">
              {user.displayName.slice(0, 1).toUpperCase()}
            </span>
            <span className="user-name">{user.displayName}</span>
          </div>
        )}
        {ready && user && (
          <div className="balance-pill" title="Virtual balance">
            <span className="balance-dot" aria-hidden="true" />
            <span className="amount">
              <AnimatedNumber value={user.balanceCents} format={(v) => fmtMoney(Math.round(v))} />
            </span>
          </div>
        )}
        {ready && user ? (
          <div className="header-actions">
            <button
              className={`btn-ghost ${armed ? "armed" : ""}`}
              onClick={onReset}
              aria-label={
                armed
                  ? "Confirm account reset"
                  : "Reset account to $1,000 and clear positions"
              }
            >
              {armed ? (
                "Confirm reset?"
              ) : (
                <>
                  <ResetIcon />
                  Reset
                </>
              )}
            </button>
            <button className="btn-ghost" onClick={() => logout().catch(() => {})}>
              Sign out
            </button>
          </div>
        ) : ready ? (
          <button className="btn btn-primary btn-header" onClick={() => openAuth("login")}>
            Sign in
          </button>
        ) : null}
      </div>
    </header>
  );
}
