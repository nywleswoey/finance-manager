import React, { useState } from "react";
import { post } from "./api.js";
import Overview from "./modules/portfolio/Overview.jsx";
import Holdings from "./modules/portfolio/Holdings.jsx";
import Performance from "./modules/portfolio/Performance.jsx";
import Dividends from "./modules/portfolio/Dividends.jsx";
import Options from "./modules/portfolio/Options.jsx";
import Transactions from "./modules/portfolio/Transactions.jsx";

const TABS = {
  Overview: Overview,
  Holdings: Holdings,
  Performance: Performance,
  Dividends: Dividends,
  Options: Options,
  Transactions: Transactions,
};

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [ver, setVer] = useState(0);            // bump to remount active tab
  const View = TABS[tab];

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

  return (
    <div className="app">
      <div className="side">
        <div className="brand">📊 MyApp</div>
        <div className="navitem on">Portfolio</div>
        <div className="navitem dim">Net Worth</div>
        <div className="navitem dim">Budget</div>
        <div className="navitem dim">Settings</div>
      </div>
      <div className="main">
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
      </div>
    </div>
  );
}
