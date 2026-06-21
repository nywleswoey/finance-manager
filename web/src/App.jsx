import React, { useState } from "react";
import Overview from "./modules/portfolio/Overview.jsx";
import Holdings from "./modules/portfolio/Holdings.jsx";
import Performance from "./modules/portfolio/Performance.jsx";
import Dividends from "./modules/portfolio/Dividends.jsx";
import Options from "./modules/portfolio/Options.jsx";
import Transactions from "./modules/portfolio/Transactions.jsx";
import Reconciliation from "./modules/portfolio/Reconciliation.jsx";

const TABS = {
  Overview: Overview,
  Holdings: Holdings,
  Performance: Performance,
  Dividends: Dividends,
  Options: Options,
  Transactions: Transactions,
  Reconciliation: Reconciliation,
};

export default function App() {
  const [tab, setTab] = useState("Overview");
  const View = TABS[tab];
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
        </div>
        <View />
      </div>
    </div>
  );
}
