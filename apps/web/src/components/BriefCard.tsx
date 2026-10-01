"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { fmtDate } from "@/lib/format";
import type { CasePoint } from "@meridian/contracts";

/* superscript citation number → anchors to the numbered row in the
   sources list below */
function Cite({ n }: { n: number }) {
  return (
    <a className="cite" href={`#intel-src-${n}`}>
      {n}
    </a>
  );
}

function CaseList({
  points,
  label,
  variant,
}: {
  points: CasePoint[];
  label: string;
  variant: "bull" | "bear";
}) {
  if (points.length === 0) return null;
  return (
    <div className={`case-col ${variant}`}>
      <div className="case-col-label">{label}</div>
      <ul className="case-list">
        {points.map((p, i) => (
          <li key={i} className="case-point">
            {p.claim}
            {p.citation != null && <Cite n={p.citation} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BriefCard({ slug }: { slug: string }) {
  const { user } = useAuth();
  const qc = useQueryClient();

  const { data: brief, isLoading, isError, error } = useQuery({
    queryKey: ["market", slug, "brief"],
    queryFn: () => api.marketBrief(slug),
  });

  const generate = useMutation({
    mutationFn: () => api.generateBrief(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["market", slug, "brief"] });
    },
  });

  const genLabel = generate.isPending ? "Generating… (~1 min)" : "Generate brief";
  const genError =
    generate.error instanceof Error ? generate.error.message : null;

  if (isLoading) {
    return (
      <section className="card brief-card" aria-busy="true">
        <div className="intel-label">AI brief</div>
        <div className="brief-skels">
          <div className="skel" aria-hidden="true" />
          <div className="skel" aria-hidden="true" />
          <div className="skel" aria-hidden="true" />
        </div>
      </section>
    );
  }

  if (isError) {
    return (
      <section className="card brief-card">
        <div className="intel-label">AI brief</div>
        <div className="intel-error">
          {error instanceof Error ? error.message : "Couldn't load the brief."}
        </div>
      </section>
    );
  }

  if (!brief) {
    return (
      <section className="card brief-card">
        <div className="brief-empty">
          <div>
            <div className="intel-label">AI brief</div>
            <p className="brief-empty-copy">
              A generated research note for this market — bull/bear case,
              upcoming catalysts, and cited sources. Generation runs a local
              model and takes about a minute.
            </p>
          </div>
          <div className="brief-empty-actions">
            <button
              className="btn-mini"
              onClick={() => generate.mutate()}
              disabled={!user || generate.isPending}
            >
              {genLabel}
            </button>
            {!user && <span className="brief-hint">Sign in first</span>}
          </div>
        </div>
        {genError && <div className="intel-error">{genError}</div>}
      </section>
    );
  }

  const generatedAt = brief.generatedAt
    ? new Date(brief.generatedAt).toLocaleString("en-US")
    : null;

  return (
    <section className="card brief-card">
      <div className="brief-top">
        <div className="intel-label">AI brief</div>
        <span className="intel-glyph" aria-hidden="true">
          ✦
        </span>
      </div>
      <h3 className="brief-headline">{brief.headline}</h3>
      <p className="brief-summary">{brief.summary}</p>

      {(brief.bullish.length > 0 || brief.bearish.length > 0) && (
        <div className="brief-cases">
          <CaseList points={brief.bullish} label="Bull case" variant="bull" />
          <CaseList points={brief.bearish} label="Bear case" variant="bear" />
        </div>
      )}

      {brief.catalysts.length > 0 && (
        <div className="brief-catalysts">
          <div className="intel-label">Catalysts</div>
          <ul className="catalyst-list">
            {brief.catalysts.map((c, i) => (
              <li key={i} className="catalyst-row">
                <span className="catalyst-what">
                  {c.what}
                  {c.citation != null && <Cite n={c.citation} />}
                </span>
                {c.whenHint && <span className="when-chip">{c.whenHint}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {brief.sourceNote && <p className="brief-note">{brief.sourceNote}</p>}

      {brief.sources.length > 0 && (
        <div className="brief-sources">
          <div className="intel-label">Sources</div>
          <ol className="src-list">
            {brief.sources.map((s) => (
              <li key={s.idx} id={`intel-src-${s.idx}`} className="src-row">
                <span className="src-idx">[{s.idx}]</span>
                <a
                  className="src-title"
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {s.title}
                </a>
                <span className="src-meta">
                  {s.publisher}
                  {s.publishedAt && <> · {fmtDate(s.publishedAt)}</>}
                </span>
                <span className={`qbadge q-${s.quality}`}>{s.quality}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="brief-foot">
        <span className="brief-meta">
          {brief.model && <>via {brief.model}</>}
          {brief.model && generatedAt && " · "}
          {generatedAt && <>generated {generatedAt}</>}
        </span>
        <button
          className="btn-mini"
          onClick={() => generate.mutate()}
          disabled={generate.isPending}
        >
          {generate.isPending ? "Generating… (~1 min)" : "Regenerate"}
        </button>
      </div>
      {genError && <div className="intel-error">{genError}</div>}
    </section>
  );
}
