import React, { useEffect, useState } from "react";
import posthog from "posthog-js";
import { post } from "./api.js";
import { useAuth } from "./auth.jsx";
import Overview from "./modules/portfolio/Overview.jsx";
import Holdings from "./modules/portfolio/Holdings.jsx";
import Performance from "./modules/portfolio/Performance.jsx";
import Dividends from "./modules/portfolio/Dividends.jsx";
import Options from "./modules/portfolio/Options.jsx";
import Transactions from "./modules/portfolio/Transactions.jsx";
import NetWorth from "./modules/networth/NetWorth.jsx";
import SpendOverview from "./modules/spending/Overview.jsx";
import SpendByCategory from "./modules/spending/ByCategory.jsx";
import SpendTransactions from "./modules/spending/Transactions.jsx";
import SpendRecurring from "./modules/spending/Recurring.jsx";
import SpendClassify from "./modules/spending/Classify.jsx";

const TABS = {
  Overview: Overview,
  Holdings: Holdings,
  Performance: Performance,
  Dividends: Dividends,
  Options: Options,
  Transactions: Transactions,
};

const SPEND_TABS = {
  Overview: SpendOverview,
  "By Category": SpendByCategory,
  Classify: SpendClassify,
  Recurring: SpendRecurring,
  Transactions: SpendTransactions,
};

/**
 * Which tabs a section owns, for the phone app bar's picker. Net Worth has none, which is
 * why the lookup can come back undefined rather than empty: an empty `<select>` is a
 * control that does nothing, so the bar renders the section's name instead.
 */
const SECTION_TABS = { Portfolio: TABS, Spending: SPEND_TABS };

/**
 * How long refresh's status stays on screen, in ms — the prototype's number.
 *
 * Transient by design rather than by decoration. The drawer beat a bottom section bar on a
 * vertical budget (48px against 147px, 181px with the home bar), and a status line that
 * never leaves spends that budget for the rest of the session. It applies at every width,
 * because the alternative is a `matchMedia` branch for a four-second string.
 *
 * Failures share the clock. "refresh failed: …" is not actionable where it sits — you
 * retry by tapping the control again — so a second code path to keep it would buy nothing.
 *
 * `tests/shell.spec.js` cross-references this number rather than importing it: it is what
 * lets that spec tell "the strip went because the section changed" from "the strip went
 * because the clock ran out".
 */
const STATUS_MS = 4000;

export default function App() {
  const [section, setSection] = useState("Portfolio");
  const [tab, setTab] = useState("Overview");
  const [spendTab, setSpendTab] = useState("Overview");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [ver, setVer] = useState(0);            // bump to remount active tab
  // The whole state cost of the phone navigation shell. Below 640px the sidebar is an
  // off-canvas drawer behind the app bar's `☰`; at every other width this is dead weight,
  // because the rail is never hidden and nothing reads it.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const View = TABS[tab];
  const SpendView = SPEND_TABS[spendTab];
  const { user, logout } = useAuth() || {};
  // Server decides; we only render. /api/spending/* returns 403 regardless of what we draw.
  const canSpend = (user?.features || []).includes("spending");
  // Losing the capability mid-session must not leave the user staring at an empty pane.
  const activeSection = section === "Spending" && !canSpend ? "Portfolio" : section;

  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), STATUS_MS);
    return () => clearTimeout(t);
  }, [msg]);

  async function refreshPrices() {
    setBusy(true);
    setMsg("");
    try {
      const r = await post("/api/refresh-prices");
      let m = `${r.ok} updated`;
      if (r.fail) m += `, ${r.fail} failed` + (r.failed?.length ? ` (${r.failed.join(", ")})` : "");
      setMsg(m);
      setVer((v) => v + 1);                      // refetch with fresh prices
      posthog.capture("prices_refreshed", { updated: r.ok, failed: r.fail || 0 });
    } catch (e) {
      setMsg("refresh failed: " + e.message);
      posthog.capture("prices_refreshed", { updated: 0, failed: 1 });
    } finally {
      setBusy(false);
    }
  }

  // One handler behind both section controls — the rail at desktop and the drawer on a
  // phone are the same markup, so there is only ever one of these to keep in step.
  function chooseSection(name) {
    setSection(name);
    setDrawerOpen(false);           // a no-op above 640px, where nothing opened
    posthog.capture("section_navigated", { section: name });
  }

  // Likewise for the tab strip and the app bar's `<select>`: two controls, one code path,
  // which is what keeps the analytics event from firing on one of them and not the other.
  function chooseTab(name) {
    if (activeSection === "Portfolio") {
      setTab(name);
      posthog.capture("portfolio_tab_changed", { tab: name });
    } else {
      setSpendTab(name);
    }
  }

  const navItem = (name, testid) => (
    <div className={"navitem" + (activeSection === name ? " on" : "")}
         data-testid={testid} onClick={() => chooseSection(name)}>{name}</div>
  );

  const barTabs = SECTION_TABS[activeSection];
  const barTab = activeSection === "Portfolio" ? tab : spendTab;
  // Refresh is a Portfolio control and stays one — the phone shell moves it, it does not
  // promote it. Its status strip below the bar is gated on the same expression.
  const canRefresh = activeSection === "Portfolio";

  return (
    <div className="app">
      <div className={"side" + (drawerOpen ? " on" : "")}>
        <div className="brand">📊 MyApp</div>
        {navItem("Portfolio", "nav-portfolio")}
        {navItem("Net Worth", "nav-networth")}
        {canSpend && navItem("Spending", "nav-spending")}
        <div className="navitem dim">Settings</div>
        {user && (
          <div className="side-user">
            <div className="side-email" title={user.email}>{user.email}</div>
            <button className="logout-btn" onClick={logout}>Sign out</button>
          </div>
        )}
      </div>
      {/* The drawer's dismissal. Absolutely positioned inside the shell rather than fixed
          to the viewport, and `aria-hidden` because it duplicates `☰` and the section
          items rather than offering anything of its own. */}
      <div className={"scrim" + (drawerOpen ? " on" : "")} data-testid="scrim"
           aria-hidden="true" onClick={() => setDrawerOpen(false)} />
      {/* The phone app bar. In the markup at every width and `display: none` above 640px:
          one component and one code path, rather than a `matchMedia` branch that would
          make "desktop is unchanged" a claim about JS instead of about layout. */}
      <div className="bar">
        <button className="bar-btn" data-testid="menu" aria-label="Navigation menu"
                aria-expanded={drawerOpen} onClick={() => setDrawerOpen((o) => !o)}>☰</button>
        {barTabs
          ? <select className="tabsel" data-testid="tabsel" aria-label="View"
                    value={barTab} onChange={(e) => chooseTab(e.target.value)}>
              {Object.keys(barTabs).map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          : <span className="bar-title">{activeSection}</span>}
        {canRefresh && (
          <button className="bar-btn" data-testid="bar-refresh" aria-label="Refresh prices"
                  onClick={refreshPrices} disabled={busy}>{busy ? "…" : "↻"}</button>
        )}
      </div>
      {/* Refresh's status on a phone: a strip *between* the bar and the pane, so it pushes
          content down instead of covering the first row of it. A flex child of the shell,
          never an overlay — which is also why it cannot collide with the home bar. Above
          640px this is `display: none` and the same string renders in `.tabs-right`.

          Gated on `canRefresh`, not on `msg` alone. `.refresh-msg` lives inside the
          Portfolio branch, so at desktop leaving the section takes the message with it; the
          same gate here is what stops "12 updated" sitting above Net Worth, reporting on a
          control that is not on screen. `STATUS_MS` would clear it seconds later either
          way — which is exactly why the gate has to be written rather than relied on. */}
      {canRefresh && msg && <div className="toast" role="status">{msg}</div>}
      <div className="main">
        {activeSection === "Portfolio" && (
          <>
            <div className="tabs">
              {Object.keys(TABS).map((t) => (
                <div key={t} className={"tab" + (t === tab ? " on" : "")}
                     onClick={() => chooseTab(t)}>
                  {t}
                </div>
              ))}
              <div className="tabs-right">
                {msg && <span className="refresh-msg">{msg}</span>}
                <button className="refresh-btn" onClick={refreshPrices} disabled={busy}>
                  {busy ? "Refreshing…" : "↻ Refresh prices"}
                </button>
              </div>
            </div>
            <View key={ver} />
          </>
        )}
        {activeSection === "Net Worth" && <NetWorth />}
        {activeSection === "Spending" && (
          <>
            <div className="tabs">
              {Object.keys(SPEND_TABS).map((t) => (
                <div key={t} className={"tab" + (t === spendTab ? " on" : "")}
                     onClick={() => chooseTab(t)}>
                  {t}
                </div>
              ))}
            </div>
            <SpendView />
          </>
        )}
      </div>
    </div>
  );
}
