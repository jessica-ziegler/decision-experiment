import { useCallback, useEffect, useRef, useState } from "react";
import type { ConnectionStatus, ExperimentState } from "./types";

// sessionStorage is per tab, so every tab is its own participant (handy for
// testing 3 humans on one machine), while a reload keeps the same seat.
const PID_KEY = "gdc_participant_id";

export function useExperiment() {
  const [state, setState] = useState<ExperimentState | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [deadline, setDeadline] = useState<number | null>(null); // performance.now() based
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let attempt = 0;
    let retryTimer: number | undefined;
    let errorTimer: number | undefined;

    const connect = () => {
      const pid = sessionStorage.getItem(PID_KEY);
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(
        `${proto}://${location.host}/ws${pid ? `?pid=${encodeURIComponent(pid)}` : ""}`,
      );
      wsRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case "welcome":
            sessionStorage.setItem(PID_KEY, msg.participant_id);
            break;
          case "state":
            setDeadline(msg.remaining_ms != null ? performance.now() + msg.remaining_ms : null);
            setState(msg as ExperimentState);
            break;
          case "chat":
            setState((s) =>
              s && !s.messages.some((m) => m.id === msg.message.id)
                ? { ...s, messages: [...s.messages, msg.message] }
                : s,
            );
            break;
          case "error":
            setError(msg.message);
            window.clearTimeout(errorTimer);
            errorTimer = window.setTimeout(() => setError(null), 4000);
            break;
        }
      };
      ws.onclose = (event) => {
        if (stopped) return;
        if (event.code === 4000) {
          setStatus("replaced"); // same participant opened in another tab
          return;
        }
        setStatus("reconnecting");
        retryTimer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt++, 8000));
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearTimeout(errorTimer);
      wsRef.current?.close();
    };
  }, []);

  const send = useCallback((payload: object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }, []);

  const sendChat = useCallback((text: string) => send({ type: "chat", text }), [send]);
  const vote = useCallback((target: string) => send({ type: "vote", target }), [send]);

  return { state, status, error, deadline, sendChat, vote };
}

export function leaveAndRejoin() {
  sessionStorage.removeItem(PID_KEY);
  location.reload();
}

/** Re-renders every 250 ms and returns ms left until `deadline`. */
export function useRemaining(deadline: number | null): number | null {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (deadline == null) return;
    const id = window.setInterval(() => setNow(performance.now()), 250);
    return () => window.clearInterval(id);
  }, [deadline]);
  return deadline == null ? null : Math.max(0, deadline - now);
}
