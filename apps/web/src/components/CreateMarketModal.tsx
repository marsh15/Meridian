"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CATEGORIES } from "@/lib/format";
import { useModalLifecycle } from "@/hooks/useModalLifecycle";

function CloseIcon() {
  return (
    <svg viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M2 2l10 10M12 2L2 12"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function CreateMarketModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [customCat, setCustomCat] = useState("");
  const [initialYes, setInitialYes] = useState(50);
  const { closing, close } = useModalLifecycle(onClose);

  const minDate = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const form = new FormData(e.currentTarget);
    try {
      const { market } = await api.createMarket({
        question: form.get("question"),
        category: category === "__other__" ? customCat : category,
        closesAt: form.get("closesAt"),
        description: form.get("description"),
        resolution: form.get("resolution"),
        initialYes: Number(initialYes),
      });
      // the grid, palette, and categories page all read ["markets"]; a fresh
      // market must appear there even inside the 5s staleTime window
      qc.invalidateQueries({ queryKey: ["markets"] });
      onClose();
      router.push(`/market/${market.slug}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      setBusy(false);
    }
  }

  return (
    <div className={`modal-overlay ${closing ? "closing" : ""}`} onClick={close}>
      <div
        className="modal card modal-lg"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Create a market"
      >
        <button className="modal-x" onClick={close} aria-label="Close">
          <CloseIcon />
        </button>

        <h2 className="modal-title">Create a market</h2>
        <p className="modal-sub">
          Ask a yes/no question the crowd can price. You set the opening odds —
          and you&apos;ll be the one to resolve it.
        </p>

        <form onSubmit={submit} className="form">
          <label className="field">
            <span>Question</span>
            <textarea
              name="question"
              rows={2}
              placeholder="Will X happen by Y?"
              required
              minLength={10}
              maxLength={240}
              autoFocus
            />
          </label>

          <div className="field-row">
            <label className="field">
              <span>Category</span>
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
                <option value="__other__">Other…</option>
              </select>
            </label>
            <label className="field">
              <span>Close date</span>
              <input name="closesAt" type="date" required min={minDate} />
            </label>
          </div>

          {category === "__other__" && (
            <label className="field">
              <span>Custom category</span>
              <input
                value={customCat}
                onChange={(e) => setCustomCat(e.target.value)}
                placeholder="e.g. Awards, Space, Local"
                maxLength={40}
                required
              />
            </label>
          )}

          <label className="field">
            <span>Description</span>
            <textarea name="description" rows={3} placeholder="Background and context for traders" />
          </label>

          <label className="field">
            <span>Resolution rules</span>
            <textarea
              name="resolution"
              rows={2}
              placeholder="Resolves YES if… (be specific)"
            />
          </label>

          <div className="field">
            <span>Opening YES price</span>
            <div className="slider-row">
              <input
                type="range"
                min={5}
                max={95}
                value={initialYes}
                onChange={(e) => setInitialYes(Number(e.target.value))}
                aria-label="Opening YES price"
              />
              <b className="slider-value">
                Yes {initialYes}¢ <i>/ No {100 - initialYes}¢</i>
              </b>
            </div>
          </div>

          {error && <div className="form-error">{error}</div>}

          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy ? "Creating…" : "Open this market"}
          </button>
        </form>
      </div>
    </div>
  );
}
