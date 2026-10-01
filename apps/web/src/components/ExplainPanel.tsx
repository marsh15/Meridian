"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Driver, Explanation } from "@meridian/contracts";

/* same ids/labels as the ChartCard range chips */
const RANGE_LABELS: Record<string, string> = {
  "1h": "1H",
  "6h": "6H",
  "1d": "1D",
  "1w": "1W",
  "1m": "1M",
  all: "ALL",
};

const DRIVER_LABELS: Record<Driver["kind"], string> = {
  trade_flow: "Trade flow",
  news: "News",
  lifecycle: "Lifecycle",
  liquidity: "Liquidity",
  other: "Other",
};

function fmtWindowTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

function explainError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Sign in to use this";
    if (err.status === 503) return "Not configured (LLM_BASE_URL)";
    return err.message; // 429 / 502 come back human-readable
  }
  return err instanceof Error ? err.message : "Request failed";
}

export default function ExplainPanel({
  slug,
  range,
}: {
  slug: string;
  range: string;
}) {
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const rangeRef = useRef(range);
  const label = RANGE_LABELS[range] ?? range.toUpperCase();

  const { mutate, reset, isPending, isError, error } = useMutation({
    mutationFn: (r: string) => api.explainMove(slug, r),
    onSuccess: (data, r) => {
      // a slow response for an abandoned range must not paint a stale
      // narrative under the new window
      if (r === rangeRef.current) setExplanation(data.explanation);
    },
  });

  /* the narrative is range-specific — switching the window collapses the
     panel back to the idle trigger (in-flight state from the old range
     goes with it) */
  useEffect(() => {
    rangeRef.current = range;
    setExplanation(null);
    reset();
  }, [range, reset]);

  return (
    <div className="explain">
      <div className="explain-head">
        <button
          className="explain-trigger"
          onClick={() => mutate(range)}
          disabled={isPending}
        >
          <span className="explain-spark" aria-hidden="true">
            ✦
          </span>
          {isPending ? `Analyzing the ${label} range…` : "Explain this range"}
        </button>
        {explanation && (
          <span className={`conf conf-${explanation.confidence}`}>
            {explanation.confidence} confidence
          </span>
        )}
      </div>

      {isPending && !explanation && (
        <p className="explain-pending">
          Local models take a minute or two — hang tight.
        </p>
      )}
      {isError && error && (
        <p className="explain-error">{explainError(error)}</p>
      )}

      {explanation && (
        <div className="explain-body">
          <p className="explain-narrative">{explanation.narrative}</p>

          {explanation.drivers.length > 0 && (
            <div className="driver-chips">
              {explanation.drivers.map((d, i) => (
                <span key={i} className="driver-chip" title={d.evidence}>
                  <span className="driver-kind">{DRIVER_LABELS[d.kind]}</span>
                  <span className="driver-weight">
                    {Math.round(d.weight * 100)}%
                  </span>
                </span>
              ))}
            </div>
          )}

          <div className="explain-window">
            Window {fmtWindowTime(explanation.window.from)} →{" "}
            {fmtWindowTime(explanation.window.to)}
          </div>

          {explanation.sources.length > 0 && (
            <div className="explain-sources">
              {explanation.sources.map((s) => (
                <a key={s.idx} href={s.url} target="_blank" rel="noreferrer">
                  {s.title}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
