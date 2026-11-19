import type { ExperimentState } from "../types";
import { leaveAndRejoin } from "../useExperiment";
import { PlayerBadge, playerColor } from "./PlayerBadge";

const TIE_BREAK_NOTE = {
  earlier_rounds: "The final vote was tied; the tie was broken by the earlier round's votes.",
  random: "The vote was tied in every round; the Decision Maker was chosen at random among the tied participants.",
} as const;

export function Results({ state }: { state: ExperimentState }) {
  const result = state.result!;
  const winner = result.decision_maker;
  const max = Math.max(1, ...state.round_results.flatMap((r) => Object.values(r.tally)));

  return (
    <div className="card results">
      <div className="eyebrow">Elected Decision Maker</div>
      <div className="winner" style={{ color: playerColor(winner) }}>
        {winner}
        {winner === state.you && <span className="winner-you">That's you!</span>}
      </div>
      {result.tie_break && <p className="muted">{TIE_BREAK_NOTE[result.tie_break]}</p>}

      <div className="tallies">
        {state.round_results.map((rr) => (
          <div key={rr.round} className="tally">
            <h3>
              Round {rr.round}
              {rr.round === state.total_rounds ? " (decisive)" : ""}
            </h3>
            {Object.entries(rr.tally).map(([label, n]) => (
              <div key={label} className="tally-row">
                <PlayerBadge label={label} you={label === state.you} />
                <div className="tally-bar">
                  <div style={{ width: `${(n / max) * 100}%`, background: playerColor(label) }} />
                </div>
                <span className="tally-n">{n}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      <p className="muted">Thank you for taking part. You can close this tab now.</p>
      <button className="link-btn" onClick={leaveAndRejoin}>
        Join a new session
      </button>
    </div>
  );
}
