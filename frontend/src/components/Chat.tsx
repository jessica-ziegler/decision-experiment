import { Fragment, useEffect, useRef, useState } from "react";
import type { ExperimentState, RoundResult } from "../types";
import { playerColor } from "./PlayerBadge";

function TallyLine({ result }: { result: RoundResult }) {
  return (
    <div className="system-line">
      <span>Votes after round {result.round}:</span>{" "}
      {Object.entries(result.tally).map(([label, n], i) => (
        <Fragment key={label}>
          {i > 0 && " · "}
          <strong style={{ color: playerColor(label) }}>{label}</strong> {n}
        </Fragment>
      ))}
    </div>
  );
}

export function ChatLog({ state }: { state: ExperimentState }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [state.messages.length, state.round_results.length]);

  const rounds = Array.from({ length: Math.max(state.round, 1) }, (_, i) => i + 1);
  return (
    <div className="chat-log">
      {rounds.map((r) => {
        const msgs = state.messages.filter((m) => m.round === r);
        const result = state.round_results.find((rr) => rr.round === r);
        return (
          <Fragment key={r}>
            <div className="round-divider">
              <span>Round {r}</span>
            </div>
            {msgs.length === 0 && state.phase === "discussion" && r === state.round && (
              <div className="system-line muted">
                {r === 1 ? "No messages yet. Say hello!" : "No messages in this round yet."}
              </div>
            )}
            {msgs.map((m) => {
              const mine = m.sender === state.you;
              return (
                <div key={m.id} className={`msg ${mine ? "mine" : ""}`}>
                  <div className="msg-sender" style={{ color: playerColor(m.sender) }}>
                    {m.sender}
                    {mine && " (you)"}
                  </div>
                  <div className="msg-bubble">{m.text}</div>
                </div>
              );
            })}
            {result && state.phase !== "results" && <TallyLine result={result} />}
          </Fragment>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}

export function ChatInput({
  enabled,
  maxLength,
  onSend,
}: {
  enabled: boolean;
  maxLength: number;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || !enabled) return;
    onSend(t);
    setText("");
  };
  return (
    <form className="chat-input" onSubmit={submit}>
      <input
        autoFocus
        value={text}
        maxLength={maxLength}
        disabled={!enabled}
        placeholder={enabled ? "Type a message…" : "Chat is closed"}
        onChange={(e) => setText(e.target.value)}
      />
      <button type="submit" disabled={!enabled || !text.trim()}>
        Send
      </button>
    </form>
  );
}
