import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import { initSentry } from "@/lib/sentry";

// No-op unless REACT_APP_SENTRY_DSN is set at build time (src/lib/sentry.js).
initSentry();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
