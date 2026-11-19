const COLORS = ["#3b6fd8", "#c2410c", "#0f8a6c", "#8b46c9", "#b4235f", "#4d7c0f"];

export function playerColor(label: string): string {
  const letter = label.trim().slice(-1).toUpperCase();
  const idx = Math.max(0, letter.charCodeAt(0) - 65);
  return COLORS[idx % COLORS.length];
}

export function PlayerBadge({ label, you }: { label: string; you?: boolean }) {
  return (
    <span className="player-badge" style={{ ["--player" as string]: playerColor(label) }}>
      <span className="player-dot">{label.slice(-1)}</span>
      {label}
      {you && <span className="you-tag">you</span>}
    </span>
  );
}
