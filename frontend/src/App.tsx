import { ChatInput, ChatLog } from "./components/Chat";
import { Header } from "./components/Header";
import { Results } from "./components/Results";
import { VotePanel } from "./components/VotePanel";
import { WaitingRoom } from "./components/WaitingRoom";
import { useExperiment } from "./useExperiment";

export default function App() {
  const { state, status, error, deadline, sendChat, vote } = useExperiment();

  if (status === "replaced") {
    return (
      <main className="page">
        <div className="card">
          <h1>Opened in another tab</h1>
          <p className="muted">This session continues in your other tab. You can close this one.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="page">
      {status === "reconnecting" && <div className="banner">Connection lost — reconnecting…</div>}
      {error && <div className="banner error">{error}</div>}

      {!state ? (
        <div className="card">
          <div className="spinner" aria-hidden />
          <p className="muted">Connecting…</p>
        </div>
      ) : state.phase === "waiting" ? (
        <WaitingRoom state={state} />
      ) : (
        <div className="experiment">
          <Header state={state} deadline={deadline} />
          {state.phase === "results" && <Results state={state} />}
          <section className="chat card">
            {state.phase === "discussion" && (
              <p className="hint">
                Discuss who should be elected <strong>Decision Maker</strong>. Voting opens when the
                timer runs out.
              </p>
            )}
            <ChatLog state={state} />
            {state.phase === "voting" ? (
              <VotePanel state={state} onVote={vote} />
            ) : state.phase === "discussion" ? (
              <ChatInput enabled maxLength={state.max_message_length} onSend={sendChat} />
            ) : null}
          </section>
        </div>
      )}
    </main>
  );
}
