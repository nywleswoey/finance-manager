import React, { useEffect, useState } from "react";
import { get, sgd, pct, cls } from "../../api.js";
import { Donut } from "../../charts.jsx";

export default function Overview() {
  const [d, setD] = useState(null);
  const [ret, setRet] = useState(null);
  const [opt, setOpt] = useState(null);
  useEffect(() => { get("/api/overview").then(setD).catch(() => setD({ error: true })); }, []);
  useEffect(() => { get("/api/return").then(setRet).catch(() => setRet({})); }, []);
  useEffect(() => { get("/api/options").then(setOpt).catch(() => setOpt({})); }, []);
  if (!d) return <div className="loading">Loading…</div>;
  if (d.error) return <div className="loading">API not reachable. Start: uvicorn server.main:app</div>;

  const pie = (obj) => Object.entries(obj).map(([k, v]) => ({ name: k, value: v.mv_sgd }));
  const mkt = pie(d.by_market), acct = pie(d.by_account).filter((x) => x.value > 0);

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Market Value" val={sgd(d.market_value_sgd)} />
        <Tile lbl="Money-weighted Return (p.a.)"
              val={ret == null ? "…" : ret.xirr_annualised == null ? "—" : pct(ret.xirr_annualised)}
              cls={ret && cls(ret.xirr_annualised)} />
        <Tile lbl="Time-weighted Return (p.a.)"
              val={ret == null ? "…" : ret.twr_annualised == null ? "—" : pct(ret.twr_annualised)}
              cls={ret && cls(ret.twr_annualised)} />
        <Tile lbl="Total P/L (cost-known)" val={sgd(d.pl_sgd)} cls={cls(d.pl_sgd)} />
        <Tile lbl="Dividends (held)" val={sgd(d.dividends_sgd)} cls="pos" />
        <Tile lbl="Options Realized P/L"
              val={opt == null ? "…" : opt.total_pl_sgd == null ? "—" : sgd(opt.total_pl_sgd)}
              cls={opt && cls(opt.total_pl_sgd)} />
        <Tile lbl="Positions" val={d.positions} />
      </div>
      <div className="grid2">
        <Donut title="Allocation by Market" data={mkt} />
        <Donut title="Allocation by Account" data={acct} />
      </div>
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")}>{val}</div></div>;
}

