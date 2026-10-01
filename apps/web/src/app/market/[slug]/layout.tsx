import type { Metadata } from "next";
import type { ReactNode } from "react";

/* Server wrapper so market pages get a real title + link preview instead
   of the site default — the page itself is a client component. The API
   fetch happens at request time; if it's unreachable (or during a build
   with no stack running) the fallback title keeps rendering working. */

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const base = process.env.MERIDIAN_API_URL ?? "http://127.0.0.1:8393";
  try {
    const res = await fetch(`${base}/api/markets/${encodeURIComponent(slug)}`, {
      next: { revalidate: 30 },
    });
    if (res.ok) {
      const body = (await res.json()) as {
        market?: { question?: string; price?: number; category?: string };
      };
      const m = body.market;
      if (m?.question) {
        return {
          title: `${m.question} — Meridian`,
          description: `YES at ${m.price}¢ · ${m.category} · trade instant-fill on Meridian`,
        };
      }
    }
  } catch {
    /* fall through to the default */
  }
  return { title: "Market — Meridian" };
}

export default function MarketLayout({ children }: { children: ReactNode }) {
  return children;
}
