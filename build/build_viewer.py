#!/usr/bin/env python3
"""Generate a self-contained portfolio.html to visually verify & reconcile transactions.

Reads build/ledger.csv + Holdings.md, computes a running share balance per
(account, ticker) in date order, and embeds everything into one HTML file with
a filterable transaction table + reconciliation badges. No server needed.
"""
import csv, json, os, re
from collections import defaultdict

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transactions & Running Balance</title>
<style>
:root{--bg:#0f1419;--panel:#161b22;--panel2:#1c232c;--line:#2b333d;--txt:#d7dde4;--mut:#8b97a5;--pos:#2ea043;--neg:#f85149;--acc:#388bfd;}
*{box-sizing:border-box}body{margin:0;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;background:var(--bg);color:var(--txt)}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;position:sticky;top:0;background:var(--bg);z-index:5}
h1{font-size:14px;margin:0;font-weight:600}
input{background:var(--panel2);border:1px solid var(--line);color:var(--txt);padding:5px 9px;border-radius:6px;font:inherit;min-width:200px}
.wrap{display:flex;height:calc(100vh - 49px)}
.side{width:300px;overflow:auto;border-right:1px solid var(--line);flex:none}
.acct{padding:7px 12px;font-weight:700;color:var(--acc);background:var(--panel);position:sticky;top:0;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.sub{padding:4px 12px 4px 20px;font-weight:600;color:var(--mut);background:#12171d;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
.tk{display:flex;justify-content:space-between;gap:8px;padding:5px 12px;cursor:pointer;border-bottom:1px solid #20262e}
.tk:hover{background:var(--panel2)} .tk.sel{background:#243044}
.tk .nm{font-weight:600} .tk .q{color:var(--mut);font-size:12px;white-space:nowrap}
.code{color:var(--mut);font-weight:400;font-size:11px;margin-left:6px} .muted{color:var(--mut)}
.main{flex:1;overflow:auto;padding:0 0 60px}
.hd{padding:14px 18px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2}
.hd h2{margin:0;font-size:16px} .hd .meta{color:var(--mut);font-size:12px;margin-top:4px}
.hd .end{color:var(--acc);font-weight:700} .hd .tgt{color:var(--mut);font-weight:700}
.hd .bk{color:var(--acc)} .hd .div{color:var(--pos);font-weight:700} td.brk{color:#b9a3e8;font-size:12px}
table{width:100%;border-collapse:collapse} th,td{padding:6px 12px;text-align:right;border-bottom:1px solid #20262e;white-space:nowrap}
th{position:sticky;top:64px;background:var(--panel);color:var(--mut);font-weight:600;z-index:1;font-size:11px;text-transform:uppercase}
td.l,th.l{text-align:left} tr:hover td{background:#1a212a}
.pos{color:var(--pos)} .neg{color:var(--neg)} .src{color:var(--mut);font-size:11px}
.balcol{font-weight:700} .endrow td{background:#1d2530 !important;border-top:2px solid var(--line)}
.empty{padding:40px;color:var(--mut);text-align:center}
</style></head><body>
<header><h1>📒 Transactions &amp; Running Balance</h1><input id="q" placeholder="filter account / ticker…" autocomplete="off"></header>
<div class="wrap"><div class="side" id="side"></div><div class="main" id="main"><div class="empty">← pick a ticker to see its transactions and the balance after each</div></div></div>
<script>
const DATA = /*DATA*/;
let sel=null;
const fmt=n=>(n==null?"":Number(n).toLocaleString(undefined,{maximumFractionDigits:4}));
const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
const SERIES=DATA.series.filter(s=>s.txns.length);

function visible(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  return SERIES.filter(s=>!q || s.bucket.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || s.ticker_code.toLowerCase().includes(q));
}
const MKT={US:"US Market",HK:"HK Market",SG:"SG Market"};
function tkRow(s){
  const row=el('div','tk'+(sel===s?' sel':''));
  row.innerHTML='<span class="nm">'+s.name+'<span class="code">'+s.ticker_code+'</span></span><span class="q">'+fmt(s.end)
    +(s.brokers.length>1?' · '+s.brokers.length+'br':'')+'</span>';
  row.onclick=()=>{sel=s;renderSide();renderMain(s);};
  return row;
}
function renderSide(){
  const side=document.getElementById('side');side.innerHTML='';
  const vis=visible();
  DATA.buckets.forEach(bk=>{
    let items=vis.filter(s=>s.bucket===bk);if(!items.length)return;
    side.appendChild(el('div','acct',bk+' ('+items.length+')'));
    if(bk==='Cash'){                                   // sub-group Cash by market
      ['US','HK','SG'].forEach(mk=>{
        const sub=items.filter(s=>s.market===mk).sort((a,b)=>a.name.localeCompare(b.name));
        if(!sub.length)return;
        side.appendChild(el('div','sub',MKT[mk]+' · '+sub.length));
        sub.forEach(s=>side.appendChild(tkRow(s)));
      });
    }else{
      items.slice().sort((a,b)=>a.name.localeCompare(b.name)).forEach(s=>side.appendChild(tkRow(s)));
    }
  });
  if(!vis.length)side.appendChild(el('div','empty','no matches'));
}
function renderMain(s){
  const m=document.getElementById('main');m.innerHTML='';
  const hd=el('div','hd');
  const tgt=s.target!=null?' &nbsp;·&nbsp; Holdings <span class="tgt">'+fmt(s.target)+'</span>':'';
  const net=s.netted?' &nbsp;·&nbsp; <span class="muted">'+s.netted+' inter-broker transfer'+(s.netted>1?'s':'')+' netted</span>':'';
  const divstr=s.div&&Object.keys(s.div).length
    ? ' &nbsp;·&nbsp; dividends <span class="div">'+Object.entries(s.div).map(([c,v])=>c+' '+fmt(v)).join(' + ')+'</span>' : '';
  hd.innerHTML='<h2><span class="bk">'+s.bucket+'</span> &nbsp;›&nbsp; '+s.name+' <span class="code">'+s.ticker_code+'</span></h2>'
    +'<div class="meta">'+s.txns.length+' transactions across '+s.brokers.length+' brokerage'+(s.brokers.length>1?'s':'')
    +' ('+s.brokers.join(', ')+') &nbsp;·&nbsp; final balance <span class="end">'+fmt(s.end)+'</span>'+tgt+divstr+net+'</div>';
  m.appendChild(hd);
  const tb=el('table');
  tb.innerHTML='<thead><tr><th class="l">date</th><th class="l">brokerage</th><th class="l">action</th><th>qty</th><th>balance after</th><th>price</th><th>amount</th></tr></thead>';
  const body=el('tbody');
  s.txns.forEach((t,i)=>{
    const tr=el('tr',i===s.txns.length-1?'endrow':'');
    const qc=t.qty>=0?'pos':'neg';const qs=(t.qty>0?'+':'')+fmt(t.qty);
    tr.innerHTML='<td class="l">'+t.date+'</td><td class="l brk">'+t.broker+'</td><td class="l">'+t.action+'</td>'
      +'<td class="'+qc+'">'+qs+'</td><td class="balcol">'+fmt(t.bal)+'</td>'
      +'<td>'+(t.price||'')+'</td><td>'+(t.amount||'')+'</td>';
    body.appendChild(tr);
  });
  tb.appendChild(body);m.appendChild(tb);
}
document.getElementById('q').oninput=renderSide;
renderSide();
</script></body></html>"""

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")

ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}  # CWBU->SET: SGX counter renamed (Cromwell->Stoneweg)
def canon(t): return ALIAS.get(t, t)

# ---- canonical code -> display name (from symbols.csv) ----
DROP = ("Cash Dividend", "Scrip Dividend", "Cash in Lieu", "NRO")
def clean(nm):
    for d in DROP:
        nm = nm.replace(d, "")
    return re.sub(r"\s+", " ", nm).strip(" ;")
CODE2NAME = {}
sp = os.path.join(ROOT, "symbols.csv")
if os.path.exists(sp):
    agg = defaultdict(list)
    for r in csv.DictReader(open(sp)):
        for n in r["names"].split(";"):
            n = clean(n)
            if n and "(label" not in n:
                agg[r["canonical"]].append(n)
    for c, cands in agg.items():
        mixed = [n for n in cands if not n.isupper()]      # prefer Title-case over ALLCAPS
        pool = mixed or cands
        CODE2NAME[c] = min(pool, key=len)                   # shortest clean name
# current display names for renamed counters (override the shortest-name heuristic)
CODE2NAME.update({"SET": "Stoneweg European Reit",   # was CWBU (Cromwell)
                  "0P0001OOJG": "Amundi Prime USA (fund)",
                  "5E2": "Seatrium",                  # current Seatrium counter
                  "S51": "Seatrium (old S51)"})       # pre-consolidation Sembcorp Marine/Seatrium

def derive_name(raw):
    """Pull a display name out of a raw source symbol, e.g.
    'LINK REIT (00823)' -> 'LINK REIT', 'Hang Lung Properties HKD' -> 'Hang Lung Properties'."""
    s = (raw or "").strip()
    m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", s)        # name (CODE)
    if m and re.search(r"[A-Za-z]", m.group(1)):
        s = m.group(1)
    s = re.sub(r"\s+(HKD|USD|SGD|CNH)\s*$", "", s).strip(" ,.")
    if not re.search(r"[A-Za-z]", s) or re.fullmatch(r"\d{4}-\d\d", s):  # digits-only / month
        return None
    return s

def enrich_names(rows):
    """enrich HK/US names from ledger raw symbols (symbols.csv only covered SG)."""
    seen = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["asset_type"] != "stock" or not r["ticker"]:
            continue
        nm = derive_name(r["raw"])
        if nm:
            seen[canon(r["ticker"])][nm] += 1
    for code, nms in seen.items():
        if code not in CODE2NAME:                      # don't override symbols.csv SG names
            CODE2NAME[code] = max(nms, key=lambda n: (nms[n], -len(n)))

def name_of(code):
    return CODE2NAME.get(code, code)

# ---- load ledger ----
rows = list(csv.DictReader(open(os.path.join(HERE, "ledger.csv"))))
for r in rows:
    r["qty_signed"] = float(r["qty_signed"]) if r["qty_signed"] else 0.0
    r["dup"] = any(x in r["account"] for x in ("superseded", "dup", "via-iFast-dup", "via-Tiger-dup"))
enrich_names(rows)

# ---- Holdings.md targets ----
hold = {}
acct_map = {"Tiger Prime Account": "Tiger Prime", "Tiger Cash Boost": "Tiger Cash Boost",
            "Moomoo Margin Account": "Moomoo", "FSM": "FSM", "CDP": "CDP", "CPF": "CPF", "SRS": "SRS"}
cur = None
for line in open(os.path.join(ROOT, "Holdings.md")):
    s = line.strip()
    m = re.match(r"^#+\s+(.*)", s)
    if m:
        name = m.group(1).strip()
        cur = acct_map.get(name, cur if name in ("US Market", "SG Market", "HK Market") else None)
        continue
    m = re.match(r"^\|([A-Za-z0-9.]+)\|([0-9.]+)\|", s.replace(" ", ""))  # ignore trailing COMMENTS col
    if m and cur:
        hold[(cur, canon(m.group(1).upper()))] = float(m.group(2))

# ---- funding bucket: map each brokerage account -> Cash / CPF / SRS ----
# SRS/CPF authoritative records are srs-stocks / cpf-stocks (consolidated across brokers);
# the *(dup) rows duplicate them and are dropped. Everything else cash-funded -> Cash.
BUCKET = {
    "Tiger Prime": "Cash", "Tiger Cash Boost": "Cash", "Moomoo": "Cash",
    "FSM": "Cash", "CDP": "Cash", "Vickers(legacy)": "Cash",
    "CPF": "CPF", "SRS": "SRS",
}
def bucket(acct):
    if "dup" in acct or "superseded" in acct: return None
    return BUCKET.get(acct)

# ---- group by (bucket, ticker), merge across brokers, running balance ----
groups = defaultdict(list)
for r in rows:
    if r["asset_type"] not in ("stock","fund") or not r["ticker"]:
        continue
    bk = bucket(r["account"])
    if bk is None:
        continue
    groups[(bk, canon(r["ticker"]))].append(r)

def datekey(r): return (str(r["date"]), r["account"])
# Holdings target summed across accounts in the same bucket
btarget = defaultdict(float)
for (acct, tk), q in hold.items():
    bk = BUCKET.get(acct)
    if bk: btarget[(bk, tk)] += q

def is_in(a):  return "transfer in" in a or a == "transfer_in"
def is_out(a): return "transfer_out" in a or "transfer out" in a

def net_transfers(evs):
    """An inter-broker custody move within a bucket gets logged on both sides and
    double-counts. Two shapes, both cancelled so the bucket balance stays continuous:
      (a) explicit pair: receiving broker 'transfer in' + sending broker 'transfer_out'
          of equal qty (e.g. FSM logged the in, CDP logged the out).  -> O5RU
      (b) implicit: CDP 'transfer_out' of shares another broker later sold without ever
          buying (FSM never logged the in). Cancel CDP transfer_outs up to that deficit.
          -> S7OU, Z74, OU8, F17, 5CP, BTOU
    Opening balances are labelled 'open' (not transfer) so real acquisitions survive."""
    ev = list(evs); dropped = 0
    # (a) explicit transfer-in <-> transfer-out pairs
    outs = [r for r in ev if is_out(r["action"]) and r["qty_signed"] < 0]
    drop = set()
    for r in ev:
        if not (is_in(r["action"]) and r["qty_signed"] > 0):
            continue
        m = next((o for o in outs if id(o) not in drop
                  and abs(abs(o["qty_signed"]) - r["qty_signed"]) < 1e-6), None)
        if m:
            drop.add(id(r)); drop.add(id(m)); dropped += 1
    ev = [r for r in ev if id(r) not in drop]
    # (b) implicit CDP transfer-out matched to another broker's sold-without-buying deficit
    deficit = max(0.0, -sum(r["qty_signed"] for r in ev if r["account"] != "CDP"))
    if deficit > 1e-6:
        cdp_outs = [r for r in ev if r["account"] == "CDP" and is_out(r["action"]) and r["qty_signed"] < 0]
        cdp_outs.sort(key=lambda r: 0 if abs(abs(r["qty_signed"]) - deficit) < 1e-6 else 1)  # exact match first
        drop2 = set(); rem = deficit
        for r in cdp_outs:
            if rem <= 1e-6: break
            if abs(r["qty_signed"]) <= rem + 1e-6:
                drop2.add(id(r)); rem -= abs(r["qty_signed"]); dropped += 1
        ev = [r for r in ev if id(r) not in drop2]
    return ev, dropped

# ---- dividends per (bucket, ticker) from dividends.csv ----
DIV_BUCKET = {"Tiger Prime": "Cash", "Tiger Cash Boost": "Cash", "Moomoo": "Cash",
              "FSM": "Cash", "CDP": "Cash", "CPF": "CPF", "SRS": "SRS"}
divs = defaultdict(lambda: defaultdict(float))   # (bucket,ticker) -> {ccy: total}
dpath = os.path.join(HERE, "dividends.csv")
if os.path.exists(dpath):
    for r in csv.DictReader(open(dpath)):
        bk = DIV_BUCKET.get(r["account"])
        if not bk: continue
        divs[(bk, canon(r["ticker"]))][r["currency"]] += float(r["gross"])

series = []
for (bk, tk), evs in groups.items():
    evs.sort(key=datekey)
    evs, npair = net_transfers(evs)
    evs.sort(key=datekey)
    bal = 0.0
    txns = []
    for r in evs:
        bal += r["qty_signed"]
        txns.append({
            "date": r["date"], "broker": r["account"], "action": r["action"],
            "qty": round(r["qty_signed"], 4), "bal": round(bal, 4),
            "price": r["price"], "amount": r["amount"], "source": r["source"],
        })
    mkt = next((r["market"] for r in evs if r["market"]), "") or \
          ("HK" if tk.isdigit() else ("US" if re.fullmatch(r"[A-Z.]+", tk) else "SG"))
    div = {c: round(v, 2) for c, v in divs.get((bk, tk), {}).items() if abs(v) > 1e-6}
    series.append({"bucket": bk, "market": mkt, "ticker": tk, "name": name_of(tk),
                   "ticker_code": tk, "end": round(bal, 4),
                   "target": round(btarget.get((bk, tk), 0), 4) if (bk, tk) in btarget else None,
                   "brokers": sorted({t["broker"] for t in txns}),
                   "netted": npair, "div": div, "txns": txns})

BORDER = {"Cash": 0, "CPF": 1, "SRS": 2}
series.sort(key=lambda s: (BORDER.get(s["bucket"], 9), s["ticker"]))
data = {"series": series, "buckets": ["Cash", "CPF", "SRS"]}

html = HTML_TEMPLATE.replace("/*DATA*/", json.dumps(data))
out = os.path.join(ROOT, "portfolio.html")
open(out, "w").write(html)
print(f"wrote {out}  ({len(series)} bucket-ticker series, {len(rows)} ledger rows)")
for bk in data["buckets"]:
    print(f"  {bk}: {sum(1 for s in series if s['bucket']==bk and s['txns'])} tickers")
