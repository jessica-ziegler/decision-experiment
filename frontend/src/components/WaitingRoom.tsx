import type { ExperimentState } from "../types";

function duration(seconds: number): string {
  if (seconds % 60 === 0) {
    const m = seconds / 60;
    return m === 1 ? "about one minute" : `about ${m} minutes`;
  }
  return `about ${Math.round(seconds)} seconds`;
}

export function WaitingRoom({ state }: { state: ExperimentState }) {
  const letters = Array.from({ length: state.group_size }, (_, i) => String.fromCharCode(65 + i));
  const playerList = `Player ${letters.slice(0, -1).join(", ")} and ${letters.at(-1)}`;
  const rounds = state.total_rounds === 1 ? "one short round" : `${state.total_rounds} short rounds`;

  // Deliberately shows no participant counts: in the AI conditions a count of
  // humans would reveal the composition of the group (blind condition).
  return (
    <div className="card waiting">
      <div className="spinner" aria-hidden />
      <h1>Waiting for other participants…</h1>
      <p className="muted">
        The study starts automatically as soon as everyone has joined. Please keep this tab open.
      </p>
      <div className="instructions">
        <h2>What will happen</h2>
        <ol>
          <li>
            You will be placed in a group of {state.group_size} participants, shown as {playerList}.
          </li>
          <li>
            In {rounds} of text chat ({duration(state.discussion_seconds)} each), discuss who in the
            group should be elected <strong>Decision Maker</strong> for a follow-up task.
          </li>
          <li>After each round, everyone votes privately for one participant (you may vote for yourself).</li>
          <li>The vote after the final round decides. The result is shown to everyone.</li>
        </ol>
      </div>
    </div>
  );
}
