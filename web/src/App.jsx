import React, { useState } from "react";
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
import SpendTransactions from "./modules/spending/Transactions.jsx";
import SpendRecurring from "./modules/spending/Recurring.jsx";

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
  Recurring: SpendRecurring,
  Transactions: SpendTransactions,
};

export default function App() {
  const [section, setSection] = useState("Portfolio");
  const [tab, setTab] = useState("Overview");
  const [spendTab, setSpendTab] = useState("Overview");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [ver, setVer] = useState(0);            // bump to remount active tab
  const View = TABS[tab];
  const SpendView = SPEND_TABS[spendTab];
  const { user, logout } = useAuth() || {};

  async function refreshPrices() {
    setBusy(true);
    setMsg("");
    try {
      const r = await post("/api/refresh-prices");
      let m = `${r.ok} updated`;
      if (r.fail) m += `, ${r.fail} failed` + (r.failed?.length ? ` (${r.failed.join(", ")})` : "");
      setMsg(m);
      setVer((v) => v + 1);                      // refetch with fresh prices
    } catch (e) {
      setMsg("refresh failed: " + e.message);
    } finally {
      setBusy(false);
    }
  }

  const navItem = (name, testid) => (
    <div className={"navitem" + (section === name ? " on" : "")}
         data-testid={testid} onClick={() => setSection(name)}>{name}</div>
  );

  return (
    <div className="app">
      <div className="side">
        <div className="brand">📊 MyApp</div>
        {navItem("Portfolio", "nav-portfolio")}
        {navItem("Net Worth", "nav-networth")}
        {navItem("Spending", "nav-spending")}
        <div className="navitem dim">Settings</div>
        {user && (
          <div className="side-user">
            <div className="side-email" title={user.email}>{user.email}</div>
            <button className="logout-btn" onClick={logout}>Sign out</button>
          </div>
        )}
      </div>
      <div className="main">
        {section === "Portfolio" && (
          <>
            <div className="tabs">
              {Object.keys(TABS).map((t) => (
                <div key={t} className={"tab" + (t === tab ? " on" : "")} onClick={() => setTab(t)}>
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
        {section === "Net Worth" && <NetWorth />}
        {section === "Spending" && (
          <>
            <div className="tabs">
              {Object.keys(SPEND_TABS).map((t) => (
                <div key={t} className={"tab" + (t === spendTab ? " on" : "")} onClick={() => setSpendTab(t)}>
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
