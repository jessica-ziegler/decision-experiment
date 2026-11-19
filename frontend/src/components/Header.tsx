import type { ExperimentState } from "../types";
import { useRemaining } from "../useExperiment";
import { PlayerBadge } from "./PlayerBadge";

function formatMs(ms: number): string {
  const s = Math.ceil(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function Header({ state, deadline }: { state: ExperimentState; deadline: number | null }) {
  const remaining = useRemaining(deadline);
  const duration = state.phase_duration_ms;
  const progress = remaining != null && duration ? remaining / duration : 0;

  const phaseLabel =
    state.phase === "discussion"
      ? `Round ${state.round} of ${state.total_rounds} · Discussion`
      : state.phase === "voting"
        ? `Round ${state.round} of ${state.total_rounds} · Voting`
        : "Final results";

  return (
    <header className="header">
      <div className="header-row">
        <div>
          <div className="eyebrow">Group Decision Study</div>
          <div className="phase">{phaseLabel}</div>
        </div>
        {remaining != null && (
          <div className={`timer ${remaining < 10_000 ? "urgent" : ""}`} aria-live="off">
            {formatMs(remaining)}
          </div>
        )}
      </div>
      {remaining != null && (
        <div className="progress">
          <div className="progress-bar" style={{ transform: `scaleX(${progress})` }} />
        </div>
      )}
      <div className="players">
        {state.players.map((p) => (
          <PlayerBadge key={p} label={p} you={p === state.you} />
        ))}
      </div>
    </header>
  );
}
