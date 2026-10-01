"use client";

/* Price + volume chart on lightweight-charts v5, restyled to the Exchange
   theme. The canvas paints itself transparent so the card surface and paper
   grain read through — colors are resolved from CSS custom properties at
   creation time, never hardcoded. Chart lifecycle lives entirely inside
   effects (hydration-safe: the server renders an empty box). */

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type AreaData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle } from "@meridian/contracts";
import { fmtVol } from "@/lib/format";

export interface ChartMarker {
  t: number;
  kind: string;
}

interface MarketChartProps {
  candles: Candle[];
  markers: ChartMarker[];
  /** current YES price in cents — patches the last candle on ticks */
  livePrice?: number | null;
  /** market.outcome, so the resolution marker points the right way */
  resolvedOutcome?: string | null;
  emptyMessage?: string;
}

/* tokens resolved at runtime → the chart follows the theme, not a copy of it */
function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* canvas gradients need rgba(); tokens for up/down/ink are hex */
function withAlpha(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const h = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export default function MarketChart({
  candles,
  markers,
  livePrice,
  resolvedOutcome,
  emptyMessage,
}: MarketChartProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<"Area"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markerRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  /* ---- create once, client-only ---- */
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;

    const muted = cssVar("--muted", "#8b8070");
    const grid = cssVar("--grid-line", "rgba(25, 21, 18, 0.07)");
    const ink = cssVar("--ink", "#191512");
    const up = cssVar("--up", "#0d7a48");
    const down = cssVar("--down", "#bd3524");
    const fontFamily = getComputedStyle(document.body).fontFamily;

    const chart = createChart(box, {
      width: box.clientWidth,
      height: box.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: muted,
        fontSize: 11,
        fontFamily,
        panes: { separatorColor: grid, separatorHoverColor: grid },
      },
      grid: {
        vertLines: { color: grid, style: LineStyle.Dotted },
        horzLines: { color: grid, style: LineStyle.Dotted },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: muted, style: LineStyle.SparseDotted, labelBackgroundColor: ink },
        horzLine: { color: muted, style: LineStyle.SparseDotted, labelBackgroundColor: ink },
      },
      localization: { locale: "en-US" },
    });

    /* YES price — full 0–100 domain, exactly like the old SVG's fixed y-scale */
    const price = chart.addSeries(AreaSeries, {
      lineWidth: 2,
      lineColor: up,
      topColor: withAlpha(up, 0.22),
      bottomColor: withAlpha(up, 0),
      priceLineVisible: true,
      priceLineWidth: 1,
      priceLineStyle: LineStyle.Dashed,
      lastValueVisible: true,
      crosshairMarkerRadius: 4,
      priceFormat: {
        type: "custom",
        formatter: (p: number) => `${Math.round(p)}¢`,
        minMove: 1,
      },
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 100 },
      }),
    });

    /* volume — its own pane (3:1), muted ink columns, dollar-formatted axis */
    const vol = chart.addSeries(
      HistogramSeries,
      {
        color: withAlpha(ink, 0.16),
        priceFormat: {
          type: "custom",
          formatter: (v: number) => fmtVol(v),
          minMove: 1,
        },
        lastValueVisible: false,
        priceLineVisible: false,
      },
      1,
    );
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.2, bottom: 0 } });
    chart.panes()[0]?.setStretchFactor(3);
    chart.panes()[1]?.setStretchFactor(1);

    const markerPlugin = createSeriesMarkers(price, []);

    chartRef.current = chart;
    priceRef.current = price;
    volRef.current = vol;
    markerRef.current = markerPlugin;

    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0]?.contentRect ?? { width: 0, height: 0 };
      if (width > 0 && height > 0) chart.resize(Math.round(width), Math.round(height));
    });
    ro.observe(box);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      priceRef.current = null;
      volRef.current = null;
      markerRef.current = null;
    };
  }, []);

  /* ---- feed data (also on range switches) + restyle by direction ---- */
  useEffect(() => {
    const price = priceRef.current;
    const vol = volRef.current;
    if (!price || !vol) return;

    const accent = cssVar("--accent", "#2747c4");
    const muted = cssVar("--muted", "#8b8070");
    const up = cssVar("--up", "#0d7a48");
    const down = cssVar("--down", "#bd3524");
    const surface = cssVar("--surface", "#fffdf8");

    price.setData(
      candles.map<AreaData>((c) => ({ time: c.t as UTCTimestamp, value: c.c })),
    );
    vol.setData(
      candles.map<HistogramData>((c) => ({ time: c.t as UTCTimestamp, value: c.v })),
    );

    /* line colored by direction — same convention as every other figure */
    const first = candles[0]?.o;
    const last = candles[candles.length - 1]?.c;
    const line = first != null && last != null && last < first ? down : up;
    price.applyOptions({
      lineColor: line,
      topColor: withAlpha(line, 0.22),
      bottomColor: withAlpha(line, 0),
      priceLineColor: line,
      crosshairMarkerBorderColor: surface,
      crosshairMarkerBackgroundColor: line,
    });

    /* lifecycle markers — open / close / resolution, clamped to the window
       and sorted (the plugin requires ascending times) */
    const from = candles[0]?.t;
    const shaped = markers
      .filter((m) => from == null || m.t >= from)
      .sort((a, b) => a.t - b.t)
      .map<SeriesMarker<UTCTimestamp>>((m) => {
        if (m.kind === "open")
          return { time: m.t as UTCTimestamp, position: "belowBar", shape: "circle", color: accent, text: "Open" };
        if (m.kind === "close")
          return { time: m.t as UTCTimestamp, position: "aboveBar", shape: "square", color: muted, text: "Close" };
        if (m.kind === "resolved") {
          const yes = resolvedOutcome !== "no";
          return {
            time: m.t as UTCTimestamp,
            position: "aboveBar",
            shape: yes ? "arrowUp" : "arrowDown",
            color: yes ? up : down,
            text: yes ? "Resolved YES" : "Resolved NO",
          };
        }
        return { time: m.t as UTCTimestamp, position: "inBar", shape: "circle", color: muted };
      });
    markerRef.current?.setMarkers(shaped);
  }, [candles, markers, resolvedOutcome]);

  /* ---- live ticks patch the last candle in place, no refetch ---- */
  useEffect(() => {
    const price = priceRef.current;
    const last = candles[candles.length - 1];
    if (!price || livePrice == null || !last) return;
    price.update({ time: last.t as UTCTimestamp, value: livePrice });
  }, [livePrice, candles]);

  return (
    <div className="chart-lwc" ref={boxRef}>
      {candles.length === 0 && emptyMessage && <div className="chart-empty">{emptyMessage}</div>}
    </div>
  );
}
