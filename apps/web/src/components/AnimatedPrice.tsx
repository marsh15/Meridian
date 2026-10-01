"use client";

import { useEffect, useRef, useState } from "react";
import {
  AnimatePresence,
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from "motion/react";

/* The two micro-animation moments (per the taste rules: tiny, meaningful,
   reduced-motion-safe) — a price/balance that tweens between values as
   ticks and fills land, flashing its direction; and the fill toast. */

export function AnimatedNumber({
  value,
  format,
  className,
  flash = false,
}: {
  value: number;
  format: (v: number) => string;
  className?: string;
  /** flash the text color toward up/down on change */
  flash?: boolean;
}) {
  const reduce = useReducedMotion();
  const mv = useMotionValue(value);
  const spring = useSpring(mv, { stiffness: 140, damping: 22 });
  const text = useTransform(spring, (v) => format(v));
  const [dir, setDir] = useState<"up" | "down" | null>(null);
  const prev = useRef(value);

  useEffect(() => {
    mv.set(value);
    if (value === prev.current) return;
    if (flash) {
      setDir(value > prev.current ? "up" : "down");
      const t = setTimeout(() => setDir(null), 650);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
  }, [value, mv, flash]);

  const cls = `${className ?? ""} ${dir ? `tick-${dir}` : ""}`.trim();
  if (reduce) return <span className={cls}>{format(value)}</span>;
  return <motion.span className={cls}>{text}</motion.span>;
}

export function AnimatedToast({
  show,
  message,
  isError,
}: {
  show: boolean;
  message: string;
  isError: boolean;
}) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key="toast"
          className={`toast motion-toast ${isError ? "error" : ""}`}
          role={isError ? "alert" : "status"}
          initial={{ y: 14, opacity: 0, scale: 0.98 }}
          animate={{ y: 0, opacity: 1, scale: 1 }}
          exit={{ y: 6, opacity: 0 }}
          transition={{ type: "spring", stiffness: 420, damping: 32 }}
        >
          {message}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
