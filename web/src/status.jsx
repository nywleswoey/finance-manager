import React from "react";

/**
 * The three placeholder states every view renders before it has rows, as one markup: the
 * `.loading` block the stylesheet pads and mutes. Written once so the copy cannot drift
 * ("API not reachable." is what `failures.spec.js` and a reader both look for).
 */
export function Loading({ what, style }) {
  return <div className="loading" style={style}>Loading{what ? ` ${what}` : ""}…</div>;
}

/** The fetch failed. `detail` is the error message, when the view kept one. */
export function Unreachable({ detail }) {
  return <div className="loading">API not reachable{detail ? `: ${detail}` : "."}</div>;
}

/** The fetch worked and there is nothing to show; the caller says what, in words. */
export function Empty({ children, style }) {
  return <div className="loading" style={style}>{children}</div>;
}
