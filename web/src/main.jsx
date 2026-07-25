import React from "react";
import { createRoot } from "react-dom/client";
import posthog from "posthog-js";
import App from "./App.jsx";
import AuthGate from "./auth.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import "./styles.css";

const POSTHOG_KEY = import.meta.env.VITE_PUBLIC_POSTHOG_KEY;
const POSTHOG_HOST = import.meta.env.VITE_PUBLIC_POSTHOG_HOST;

if (!POSTHOG_KEY && import.meta.env.DEV) {
  console.error(
    "VITE_PUBLIC_POSTHOG_KEY variable required by PostHog is missing or un-configured, " +
      "this causes events to be silently missed. " +
      "This error stops appearing once VITE_PUBLIC_POSTHOG_KEY is configured"
  );
}
if (!POSTHOG_HOST && import.meta.env.DEV) {
  console.error(
    "VITE_PUBLIC_POSTHOG_HOST variable required by PostHog is missing or un-configured, " +
      "this causes events to be silently missed. " +
      "This error stops appearing once VITE_PUBLIC_POSTHOG_HOST is configured"
  );
}

if (POSTHOG_KEY && POSTHOG_HOST) {
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    defaults: "2026-05-30",
    // Autocapture uncaught errors + unhandled promise rejections into PostHog error tracking.
    capture_exceptions: true,
  });
}

createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <AuthGate>
      <App />
    </AuthGate>
  </ErrorBoundary>
);
