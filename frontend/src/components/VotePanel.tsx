import type { ExperimentState } from "../types";
import { PlayerBadge } from "./PlayerBadge";

export function VotePanel({ state, onVote }: { state: ExperimentState; onVote: (t: string) => void }) {
  const myVote = state.my_votes[String(state.round)];
  return (
    <div className="vote-panel">
      {myVote ? (
        <p>
          You voted for <PlayerBadge label={myVote} you={myVote === state.you} />. Waiting for the others…
        </p>
      ) : (
        <>
          <p>
            <strong>Who should be the Decision Maker?</strong> Your vote is private.
          </p>
          <div className="vote-options">
            {state.players.map((p) => (
              <button key={p} className="vote-btn" onClick={() => onVote(p)}>
                <PlayerBadge label={p} you={p === state.you} />
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
