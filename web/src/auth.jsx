import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import posthog from "posthog-js";

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";
const GIS_SRC = "https://accounts.google.com/gsi/client";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

// Load Google Identity Services once.
function loadGis() {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve();
    let s = document.querySelector(`script[src="${GIS_SRC}"]`);
    if (!s) {
      s = document.createElement("script");
      s.src = GIS_SRC;
      s.async = true;
      s.defer = true;
      document.head.appendChild(s);
    }
    s.addEventListener("load", () => resolve());
    s.addEventListener("error", () => reject(new Error("failed to load Google sign-in")));
  });
}

function LoginScreen({ onCredential, error }) {
  const btn = useRef(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!CLIENT_ID) { setLoadErr("VITE_GOOGLE_CLIENT_ID is not configured"); return; }
    loadGis()
      .then(() => {
        if (cancelled) return;
        window.google.accounts.id.initialize({
          client_id: CLIENT_ID,
          callback: (resp) => onCredential(resp.credential),
        });
        window.google.accounts.id.renderButton(btn.current, {
          theme: "outline", size: "large", text: "signin_with", shape: "pill",
        });
      })
      .catch((e) => !cancelled && setLoadErr(e.message));
    return () => { cancelled = true; };
  }, [onCredential]);

  return (
    // `100svh` for a different reason than the shell's: `min-height: 100vh` leaves a
    // *scrollable* strip rather than an unreachable one, so the page rubber-bands with
    // nothing to scroll and the "centred" content sits ~32px low. No fallback pair — React
    // style keys are unique — and without `svh` this collapses to content height, uncovering
    // body's `#0f1419` behind the div's `#0f1115`. The colour drift makes the failure benign.
    <div style={{ minHeight: "100svh", display: "grid", placeItems: "center", background: "#0f1115" }}>
      <div style={{ textAlign: "center", color: "#e6e6e6", fontFamily: "system-ui, sans-serif" }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>📊</div>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 4px" }}>Portfolio</h1>
        <p style={{ color: "#8a8f98", margin: "0 0 24px", fontSize: 14 }}>Sign in to continue</p>
        <div ref={btn} style={{ display: "inline-block" }} />
        {(error || loadErr) && (
          <p style={{ color: "#f87171", marginTop: 16, fontSize: 13, maxWidth: 280 }}>{error || loadErr}</p>
        )}
      </div>
    </div>
  );
}

// Gate: blocks the app until a valid session exists. Re-renders to login on 401.
export default function AuthGate({ children }) {
  const [state, setState] = useState("loading");   // loading | out | in
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");

  async function check() {
    try {
      const r = await fetch("/api/auth/me", { credentials: "include" });
      if (r.ok) {
        const u = await r.json();
        setUser(u);
        setState("in");
        if (u?.sub) posthog.identify(u.sub, { email: u.email });
      } else { setUser(null); setState("out"); }
    } catch {
      setUser(null); setState("out");
    }
  }

  useEffect(() => {
    check();
    // any fetch elsewhere that hits 401 broadcasts this -> drop back to login
    const onExpired = () => { setUser(null); setState("out"); };
    window.addEventListener("auth-expired", onExpired);
    return () => window.removeEventListener("auth-expired", onExpired);
  }, []);

  async function onCredential(credential) {
    setError("");
    try {
      const r = await fetch("/api/auth/google", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential }),
      });
      if (r.ok) {
        await check();
        posthog.capture("user_signed_in", { method: "google" });
        return;
      }
      const reason = r.status === 403 ? "unauthorized" : "server_error";
      posthog.capture("sign_in_failed", { method: "google", reason });
      if (r.status === 403) setError("This account is not authorized.");
      else setError("Sign-in failed. Try again.");
    } catch {
      posthog.capture("sign_in_failed", { method: "google", reason: "network_error" });
      setError("Sign-in failed. Try again.");
    }
  }

  async function logout() {
    posthog.capture("user_signed_out");
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "include" }); } catch {}
    window.google?.accounts?.id?.disableAutoSelect?.();
    posthog.reset();
    setUser(null); setState("out");
  }

  if (state === "loading") {
    // Same `svh` fix as `LoginScreen`: this is the same screen with nothing painted on it yet.
    return <div style={{ minHeight: "100svh", background: "#0f1115" }} />;
  }
  if (state === "out") {
    return <LoginScreen onCredential={onCredential} error={error} />;
  }
  return <AuthCtx.Provider value={{ user, logout }}>{children}</AuthCtx.Provider>;
}
