/* Shared SSE connections, ref-counted per URL: the first subscriber
   connects, the last one out closes. Without this the home page and the
   ticker tape each opened their own /api/stream — doubled connections,
   doubled tick processing, doubled server fan-out.

   Reconnect: EventSource retries network drops itself, but a non-200 from
   the server or proxy (502 during a deploy, 503) closes it permanently.
   A closed connection is re-created with backoff, and status listeners
   let surfaces show that prices are reconnecting instead of silently
   stale. */

type MessageHandler = (e: MessageEvent) => void;
type StatusHandler = (live: boolean) => void;

interface SharedStream {
  es: EventSource | null;
  handlers: Set<MessageHandler>;
  statusHandlers: Set<StatusHandler>;
  refCount: number;
  attempts: number;
  timer: ReturnType<typeof setTimeout> | null;
}

const streams = new Map<string, SharedStream>();

function notifyStatus(s: SharedStream, live: boolean) {
  for (const h of s.statusHandlers) h(live);
}

function connect(url: string, s: SharedStream) {
  const es = new EventSource(url);
  s.es = es;
  es.addEventListener("open", () => {
    s.attempts = 0;
    notifyStatus(s, true);
  });
  es.addEventListener("tick", (e) => {
    for (const h of s.handlers) h(e as MessageEvent);
  });
  es.addEventListener("error", () => {
    // CONNECTING = browser is retrying a dropped connection — fine.
    // CLOSED = the server refused us (non-200); EventSource will not
    // retry on its own, so recreate it with backoff.
    if (es.readyState === EventSource.CLOSED) {
      notifyStatus(s, false);
      es.close();
      s.es = null;
      if (s.refCount === 0) return;
      const delay = Math.min(1000 * 2 ** s.attempts, 15_000);
      s.attempts += 1;
      s.timer = setTimeout(() => {
        if (s.refCount > 0) connect(url, s);
      }, delay);
    }
  });
}

export function subscribeStream(
  url: string,
  onMessage: MessageHandler,
  onStatus?: StatusHandler,
): () => void {
  let s = streams.get(url);
  if (!s) {
    s = {
      es: null,
      handlers: new Set(),
      statusHandlers: new Set(),
      refCount: 0,
      attempts: 0,
      timer: null,
    };
    streams.set(url, s);
  }
  const hadRefs = s.refCount > 0;
  s.refCount += 1;
  s.handlers.add(onMessage);
  if (onStatus) {
    s.statusHandlers.add(onStatus);
    // already-connected stream reports live immediately
    if (hadRefs && s.es) onStatus(true);
  }
  if (!hadRefs) connect(url, s);

  return () => {
    s.handlers.delete(onMessage);
    if (onStatus) s.statusHandlers.delete(onStatus);
    s.refCount -= 1;
    if (s.refCount === 0) {
      if (s.timer) clearTimeout(s.timer);
      s.es?.close();
      streams.delete(url);
    }
  };
}
