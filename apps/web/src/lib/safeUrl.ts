/* External links (intel citations) pass through here: anything that isn't
   a plain http(s) URL — including a hallucinated javascript: URL from the
   LLM pipeline — renders unlinked instead of clickable. */

export function safeHttpUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

/* Idempotency keys: crypto.randomUUID needs a secure context, which a
   plain-HTTP LAN demo box isn't — fall back to a random string. */
export function idempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
