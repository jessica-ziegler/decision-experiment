export type Phase = "waiting" | "discussion" | "voting" | "results";

export interface ChatMessage {
  id: number;
  round: number;
  sender: string;
  text: string;
  ts: number;
}

export interface RoundResult {
  round: number;
  tally: Record<string, number>;
}

export interface ExperimentState {
  phase: Phase;
  round: number;
  total_rounds: number;
  remaining_ms: number | null;
  phase_duration_ms: number | null;
  you: string | null;
  players: string[];
  messages: ChatMessage[];
  my_votes: Record<string, string>;
  round_results: RoundResult[];
  result: { decision_maker: string; tie_break: "earlier_rounds" | "random" | null } | null;
  max_message_length: number;
  group_size: number;
  discussion_seconds: number;
}

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "replaced";
