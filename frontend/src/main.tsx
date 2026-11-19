import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// No <StrictMode>: its double-mounted effects would open (and drop) an extra
// WebSocket in dev, briefly taking a waiting-room seat.
createRoot(document.getElementById("root")!).render(<App />);
