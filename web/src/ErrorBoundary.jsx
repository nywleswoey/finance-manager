import React from "react";
import posthog from "posthog-js";

// React swallows render/lifecycle errors, so they never reach PostHog's
// window.onerror hook. This boundary forwards them explicitly and shows a
// fallback instead of an unmounted (blank) tree.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    // posthog.init() is skipped when the VITE_PUBLIC_POSTHOG_* vars are absent (normal in
    // local dev), so reporting is best-effort: never let it throw out of componentDidCatch,
    // which would unmount the very fallback this boundary exists to show.
    try {
      posthog.captureException(error, { react_component_stack: info?.componentStack });
    } catch {
      // reporting is optional; the fallback UI is not
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="card" style={{ margin: 24 }}>
          <h3>Something went wrong</h3>
          <p>The page hit an unexpected error. Try reloading.</p>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}
