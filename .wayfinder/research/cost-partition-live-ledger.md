# The cost partition, measured against the live ledger

Resolves [#137](https://github.com/nywleswoey/finance-manager/issues/137). Companion to
[#135](https://github.com/nywleswoey/finance-manager/issues/135), which derived the partition rule
from fixtures and could not reach a database.

**Source**: local `portfolio` Postgres (docker `portfolio_db`, `localhost:5544`), replayed through
`portfolio.performance.fold_positions` with per-entering-row instrumentation.
**Scale**: 548 `txn` rows, 91 securities, 409 option trades, 76 `cdp_cost_lot` rows, **73 positions**
(the fixtures' `transactions.json` was capped at 500 rows and showed ~70).

## Method

Every row with `qty_signed > 0` is one *entering* event, assigned to exactly one of `costed` /
`free` / `unknown`, **after** `_carry_corporate_actions` and its switch-rebasing loop have run.
The partition **sums to gross units in on all 73 positions**.

Classification, in order:

1. **CDP rows** carry no price in `txn`; their cost arrives per *ticker* from `cdp_cost_lot` via
   `cdp_cost()`. So CDP entering units are matched against the ticker's total priced-lot buy
   quantity — **at position level, not per row**. A CDP `txn` row is a month-end statement diff and
   routinely aggregates several trade-dated lots (LIW's 24,600 is three lots; Z74's 8,500 is
   4,000 + 4,500), so per-row matching invents shortfalls that do not exist.
2. `classify()` returns `cash` → **costed**; `uncosted` → **unknown**.
3. `gift_in` / `gifted stock in` / `bonus` / `bonus issuance` → **free**.
4. Unpriced carry-in (`transfer_in`, `transfer in`, `open/transfer_in`, `open`, `switch_in`) →
   **costed** if a matching exit exists in the same position (an internal move), or if a corporate
   action landed a predecessor's cost; otherwise **unknown**.
5. Zero-priced `corp action` → **unknown** unless annotated (see §3).

Verdicts per #135: refuse ⟺ `costed == 0 ∧ unknown > 0`; caveat ⟺ both > 0; hero ⟺ `unknown == 0`.

## Result

**68 hero, 4 caveat, 1 refuse.** Ledger totals: 1,574,652 gross units in — 1,521,274 costed,
962 free, **52,416 unknown**.

| ticker | bucket | gross in | costed | free | unknown | %unk | verdict | held now | cost_known | invested SGD | Net P/L SGD |
|---|---|---:|---:|---:|---:|---:|---|---:|---|---:|---:|
| ASTREA6B | cash | 15,000 | 0 | 0 | 15,000 | 100.00 | refuse | 0 | False | 0.00 | — |
| C38U | cash | 6,700 | 6,200 | 417 | 83 | 1.24 | caveat | 6,700 | True | 11,121.87 | 7,756.75 |
| Q01 | cash | 68,000 | 51,000 | 0 | 17,000 | 25.00 | caveat | 17,000 | True | 50,192.02 | -6,190.17 |
| S51 | cash | 36,832 | 22,099 | 0 | 14,733 | 40.00 | caveat | 0 | True | 1,767.92 | 2,270.10 |
| SET | cash | 20,100 | 14,500 | 0 | 5,600 | 27.86 | caveat | 14,500 | True | 24,305.83 | 9,112.57 |
| 00010 | cash | 18,000 | 18,000 | 0 | 0 | 0.00 | hero | 7,000 | True | 33,988.63 | 2,235.62 |
| 00101 | cash | 18,000 | 18,000 | 0 | 0 | 0.00 | hero | 18,000 | True | 19,023.09 | 5,491.50 |
| 00468 | cash | 64,000 | 64,000 | 0 | 0 | 0.00 | hero | 0 | True | 25,343.80 | -1,637.13 |
| 00788 | cash | 23,500 | 23,500 | 0 | 0 | 0.00 | hero | 23,500 | True | 43,041.90 | -5,107.32 |
| 00823 | cash | 22,000 | 22,000 | 0 | 0 | 0.00 | hero | 6,000 | True | 136,144.95 | 7,092.14 |
| 01038 | cash | 1,500 | 1,500 | 0 | 0 | 0.00 | hero | 1,500 | True | 11,643.47 | 7,247.07 |
| 01310 | cash | 57,000 | 57,000 | 0 | 0 | 0.00 | hero | 27,000 | True | 39,289.69 | 34,898.71 |
| 01523 | cash | 64,000 | 64,000 | 0 | 0 | 0.00 | hero | 0 | True | 22,217.05 | 83,859.48 |
| 01883 | cash | 11,000 | 11,000 | 0 | 0 | 0.00 | hero | 11,000 | True | 4,644.28 | 2,147.53 |
| 0P00006FYT | cpf | 20,844.85 | 20,844.85 | 0 | 0 | 0.00 | hero | 0 | False | 0.00 | — |
| 0P0001OOJG | cpf | 409.897 | 409.897 | 0 | 0 | 0.00 | hero | 406.1092 | True | 52,956.66 | 45,126.83 |
| 1J5 | cash | 3,000 | 3,000 | 0 | 0 | 0.00 | hero | 3,000 | True | 782.00 | 412.90 |
| 3255 | cash | 1,600 | 1,600 | 0 | 0 | 0.00 | hero | 1,600 | True | 9,769.70 | -163.46 |
| 42R | cash | 3,000 | 3,000 | 0 | 0 | 0.00 | hero | 3,000 | True | 752.00 | 232.00 |
| 43Q | cash | 6,000 | 6,000 | 0 | 0 | 0.00 | hero | 0 | True | 1,322.00 | 336.74 |
| 558 | cash | 10,000 | 10,000 | 0 | 0 | 0.00 | hero | 0 | True | 5,729.19 | 2,897.74 |
| 5CP | cash | 50,000 | 50,000 | 0 | 0 | 0.00 | hero | 0 | True | 10,033.71 | 5,597.68 |
| 5E2 | cash | 1 | 1 | 0 | 0 | 0.00 | hero | 1 | True | 1.54 | 1.61 |
| 9CI | cash | 2,700 | 2,700 | 0 | 0 | 0.00 | hero | 2,700 | True | 10,071.00 | 839.70 |
| AAPL | cash | 1 | 0 | 1 | 0 | 0.00 | hero | 1 | False | 0.00 | — |
| ADQU | cash | 40,000 | 40,000 | 0 | 0 | 0.00 | hero | 0 | True | 21,100.00 | 12,162.00 |
| AMD | cash | 400 | 400 | 0 | 0 | 0.00 | hero | 0 | True | 111,126.75 | 1,281.00 |
| AMZN | cash | 0.3486 | 0 | 0.3486 | 0 | 0.00 | hero | 0.3486 | False | 0.00 | — |
| BABA | cash | 701 | 700 | 1 | 0 | 0.00 | hero | 601 | True | 130,662.00 | -32,924.45 |
| BIDU | cash | 100 | 100 | 0 | 0 | 0.00 | hero | 0 | True | 25,620.00 | -5,812.60 |
| BSL | cash | 9,000 | 9,000 | 0 | 0 | 0.00 | hero | 0 | True | 10,339.73 | -562.79 |
| BTOU | cash | 10,400 | 10,400 | 0 | 0 | 0.00 | hero | 0 | True | 3,434.21 | -2,099.48 |
| BVA | cash | 16,000 | 16,000 | 0 | 0 | 0.00 | hero | 0 | True | 27,362.00 | 1,642.91 |
| C31 | cash | 2,700 | 2,700 | 0 | 0 | 0.00 | hero | 0 | False | 0.00 | — |
| C52 | cash | 6,000 | 6,000 | 0 | 0 | 0.00 | hero | 6,000 | True | 10,213.10 | -70.70 |
| C52 | cpf | 7,200 | 7,200 | 0 | 0 | 0.00 | hero | 7,200 | True | 10,008.00 | 1,908.72 |
| CHZ | cash | 23,600 | 23,600 | 0 | 0 | 0.00 | hero | 0 | True | 18,229.14 | -6,312.33 |
| CJLU | cash | 11,000 | 11,000 | 0 | 0 | 0.00 | hero | 0 | True | 9,005.34 | 39.03 |
| CMOU | cash | 34,800 | 34,800 | 0 | 0 | 0.00 | hero | 34,800 | True | 9,980.85 | -3,487.92 |
| COIN | cash | 600 | 600 | 0 | 0 | 0.00 | hero | 400 | True | 169,732.50 | -32,260.70 |
| CRPU | cash | 12,000 | 12,000 | 0 | 0 | 0.00 | hero | 12,000 | True | 8,238.47 | 2,425.34 |
| D05 | cash | 5,880 | 5,600 | 280 | 0 | 0.00 | hero | 3,080 | True | 73,289.20 | 194,503.20 |
| D05 | cpf | 1,210 | 1,100 | 110 | 0 | 0.00 | hero | 1,210 | True | 23,151.00 | 80,274.30 |
| F17 | cash | 10,000 | 10,000 | 0 | 0 | 0.00 | hero | 0 | True | 9,281.18 | 7,540.66 |
| F34 | cash | 7,200 | 7,200 | 0 | 0 | 0.00 | hero | 7,200 | True | 24,041.85 | 6,556.15 |
| F34 | cpf | 4,000 | 4,000 | 0 | 0 | 0.00 | hero | 0 | True | 12,600.00 | 940.00 |
| H78 | cash | 1,000 | 1,000 | 0 | 0 | 0.00 | hero | 0 | True | 7,584.64 | 2,691.56 |
| HMN | cash | 153 | 0 | 153 | 0 | 0.00 | hero | 153 | False | 0.00 | — |
| HUYA | cash | 1,300 | 1,300 | 0 | 0 | 0.00 | hero | 0 | True | 24,082.80 | -20,752.20 |
| INTC | cash | 1,900 | 1,900 | 0 | 0 | 0.00 | hero | 400 | True | 170,373.00 | -3,662.38 |
| J2T | cash | 60,000 | 60,000 | 0 | 0 | 0.00 | hero | 700 | True | 22,741.07 | 729.25 |
| LIW | cash | 30,100 | 30,100 | 0 | 0 | 0.00 | hero | 0 | True | 25,511.50 | -12,123.88 |
| MR7 | cash | 31,500 | 31,500 | 0 | 0 | 0.00 | hero | 0 | True | 10,080.00 | 368.78 |
| MSFT | cash | 100 | 100 | 0 | 0 | 0.00 | hero | 0 | True | 49,959.00 | 1,281.00 |
| N2IU | cash | 3,200 | 3,200 | 0 | 0 | 0.00 | hero | 3,200 | True | 5,068.86 | 929.22 |
| NVDA | cash | 200 | 200 | 0 | 0 | 0.00 | hero | 0 | True | 37,469.25 | 643.06 |
| O39 | cash | 919 | 919 | 0 | 0 | 0.00 | hero | 919 | True | 7,823.12 | 20,671.63 |
| O5RU | cash | 66,890 | 66,890 | 0 | 0 | 0.00 | hero | 37,800 | True | 49,335.42 | 39,713.53 |
| O5RU | srs | 5,000 | 5,000 | 0 | 0 | 0.00 | hero | 5,000 | True | 5,802.00 | 4,653.66 |
| OU8 | cash | 66,200 | 66,200 | 0 | 0 | 0.00 | hero | 0 | True | 20,055.56 | -2,616.14 |
| P40U | cash | 13,500 | 13,500 | 0 | 0 | 0.00 | hero | 0 | True | 10,294.58 | -247.58 |
| PLTR | cash | 3,505 | 3,505 | 0 | 0 | 0.00 | hero | 5 | True | 160,192.94 | 16,731.86 |
| RIVN | cash | 7,300 | 7,300 | 0 | 0 | 0.00 | hero | 1,500 | True | 139,821.15 | -1,140.09 |
| S61 | cash | 1,700 | 1,700 | 0 | 0 | 0.00 | hero | 0 | True | 4,868.24 | 3,219.55 |
| S61 | srs | 5,400 | 5,400 | 0 | 0 | 0.00 | hero | 5,400 | True | 16,078.00 | 9,020.66 |
| S7OU | cash | 216,000 | 216,000 | 0 | 0 | 0.00 | hero | 0 | True | 24,864.33 | 6,408.13 |
| SV3U | cash | 15,500 | 15,500 | 0 | 0 | 0.00 | hero | 0 | True | 10,264.48 | -86.29 |
| TSLA | cash | 100 | 100 | 0 | 0 | 0.00 | hero | 0 | True | 57,004.50 | 0.00 |
| U96 | cash | 3,000 | 3,000 | 0 | 0 | 0.00 | hero | 0 | True | 5,413.01 | 3,843.35 |
| UD1U | cash | 43,900 | 43,900 | 0 | 0 | 0.00 | hero | 43,900 | True | 21,056.34 | -8,816.02 |
| UD1U | srs | 233,305 | 233,305 | 0 | 0 | 0.00 | hero | 222,205 | True | 94,276.05 | -36,781.15 |
| Z74 | cash | 27,100 | 27,100 | 0 | 0 | 0.00 | hero | 0 | True | 77,128.08 | 21,252.79 |
| Z74 | cpf | 9,900 | 9,900 | 0 | 0 | 0.00 | hero | 0 | True | 31,951.00 | 2,856.50 |
## 1. #135's six unresolved names: the carry landed in all six

Every one of `S7OU`, `5CP`, `OU8`, `Z74`, `BTOU`, `F17` pairs its unpriced carry-in leg with a
matching `sell/transfer_out` **inside the same `(bucket, security)` position** — the CDP→FSM
custodian migrations of 2020-03-28 and 2024-06-28. The cost was never lost; it stayed in the
position, exactly as `fold_positions`' grouping comment claims. **None joins C38U in the caveat
class**, and none needs an annotation.

| ticker | carry-in leg | matching exit | verdict |
|---|---|---|---|
| S7OU | txn 1124, FSM `transfer_in` 108,000 | txn 71, CDP `sell/transfer_out` −108,000 | landed |
| 5CP | txn 1413, FSM `transfer_in` 25,000 | txn 355, CDP `sell/transfer_out` −25,000 | landed |
| OU8 | txn 1415, FSM `transfer_in` 20,000 | txn 358, CDP `sell/transfer_out` −20,000 | landed |
| Z74 | txn 1125, FSM `transfer_in` 10,000 | txn 72, CDP `sell/transfer_out` −10,000 | landed |
| BTOU | txn 1414, FSM `transfer_in` 5,200 | txn 357, CDP `sell/transfer_out` −5,200 | landed |
| F17 | txn 1123, FSM `transfer_in` 5,000 | txn 68, CDP `sell/transfer_out` −5,000 | landed |

`9CI` (2,700 from C31, split) and `0P0001OOJG` (393.271 from 0P00006FYT, switch) land through
`_carry_corporate_actions` as #135 predicted.

## 2. The real caveat set is four names, not one — and the new ones are big

#135's caveat set was **C38U alone at 1.24%**. C38U's number is exactly right. Three others were
invisible from the fixtures because the gap is between the CDP *statement* rows and the CDP *cost
CSV*, and neither is in `transactions.json`.

| ticker | unknown / gross in | what is missing |
|---|---|---|
| **S51** | 14,733 / 36,832 = **40.0%** | txn 96, FSM `corp action` 2020-09-11, `price 0.0`, `gross 0.0` — 14,733 units appear from nothing with no prior S51 holding anywhere in the book |
| **SET** | 5,600 / 20,100 = **27.9%** | txn 49, CDP `open` 7,000 (2019-08-28); the only SET cost lot covers 1,400 @ 2.35 |
| **Q01** | 17,000 / 68,000 = **25.0%** | txn 129, CDP `buy` 17,000 (2021-03-28); Q01's two cost lots cover only the earlier, since-transferred-out 17,000 |
| **C38U** | 83 / 6,700 = **1.24%** | txn 428, Moomoo `buy` 83 with no price — the `uncosted_units` case, unchanged |

**Q01 is the worst of these and is still held.** Its 17,000 held units are the uncosted lot, yet
pooled averaging spreads the *other* lot's cost across them: `avg_cost` 0.9842 → `cost_basis_sgd`
**16,730.67**, entirely fabricated, and `unrealised_pl_sgd` **−70.67** reads like a precise number
about an invented basis. `realised_pl_sgd` −11,559.50 is contaminated by the same `cost_basis` term.

**SET** carries 10,653.40 SGD of income earned partly on units that cost the book nothing, so its
Net 9,112.57 is an upper bound. **S51**'s 14,733 uncosted units were all sold, making its realised
2,270.10 an upper bound too.

## 3. The refusal set is one position, and it never renders

**`ASTREA6B`** (Astrea VI Class B bond): txn 128, CDP `open` 15,000 on 2021-03-28, no cost lot at
all, transferred out 2025-10-28. `costed = 0, unknown = 15,000` → **refuse**, the only one in the
book.

It is invisible on the site: `units = 0`, `invested_native = 0`, `income_native = 0`, so
`/api/positions` drops it at `main.py:261` ("never really held") on both the open and closed lists.
Nothing links to `/api/holding?ticker=ASTREA6B`. Its coupons are not in the `dividend` table either.

So **#132's refusal state still has no reachable real instance**, and #126's fixture note stands —
it must be drawn synthetically from the rule.

## 4. The annotation list

#135 named three rows. The live ledger needs **four** hand annotations; the other five free rows are
mechanical (`gifted stock in`, `bonus issuance`) and need none.

| txn | ticker | date | account | action | qty | annotation |
|---|---|---|---|---|---:|---|
| 238 | AAPL | 2022-12-28 | Moomoo | `open/transfer_in` | 1 | free — welcome gift |
| 272 | HMN | 2023-05-28 | Moomoo | `open/transfer_in` | 153 | free — given as a dividend |
| 165 | C38U | 2021-09-28 | Moomoo | `open/transfer_in` | 417 | free — given as a dividend |
| **341** | **D05** | **2024-04-30** | **FSM** | **`corp action`** | **280** | **free — bonus shares** |

D05's 280 is new. `classify()` sends a zero-priced `corp action` to `zero`, and the only record that
it is a bonus rather than an unrecorded purchase is a **prose comment** in `performance.py`
(`PRICED_CORP_ACTION`, naming "D05's 280 bonus shares"). That is knowledge held outside the data —
exactly what #135 says belongs in the annotation.

**The same class also holds S51's 14,733, which the comment does not cover** and which nothing in
the ledger explains. Under #135's default-`unknown` polarity it must stay unknown, which is what
puts S51 in the caveat set at 40%. **Zero-priced `corp action` needs the annotation just as much as
`open/transfer_in` does** — a decision for #131.

Mechanical free rows, no annotation: AMZN txn 373/374/375 (`gifted stock in`, 0.1162 each),
BABA txn 179 (`gifted stock in`, 1), D05 cpf txn 340 (`bonus issuance`, 110).

## 5. The scrip correction does not exist

**#135's §2 is void against the live ledger.** It found four scrip rows booked free while their cash
dividend was credited, and concluded 2,171.90 of O5RU's cost was missing and "17.2% of its
unrealised P/L is fabricated". Measured: **the cost is already booked**.

There are **zero** `scrip` / `scrip dividend` / `script dividend` rows in `txn`. The four rows live
in **`cdp_cost_lot`**, as `script dividend` with a **negative** `amount`:

```
2019-03-29  O5RU  506  @1.36  −687.50
2019-06-20  O5RU  563  @1.36  −770.17
2019-12-20  O5RU  521  @1.37  −714.23
2020-10-07  O39    19  @7.81  −143.10
```

`cdp_cost()` skips only `CDP_TRANSFER`; `script dividend` is not in it, so a negative `amount`
books `invested += 687.50` like any other purchase. These rows never reach `classify()` at all —
CDP rows `continue` before `_apply_txn` (`performance.py:312`). Confirmed arithmetically: O5RU cash
`invested_native` = **49,335.42** = 10,723.52 + 27,091.00 + **687.50 + 770.17 + 714.23** + 4,937.81
+ 4,411.18.

Both legs are present and the treatment is correct: income +687.50 and invested +687.50 net to the
shares received. **These units are `costed`, and no correction is owed to O5RU (12,656.58 unrealised
stands) or O39.** The three scrip actions can stay in `ZERO_CASH`; the discriminator #135 proposed
(price present, gross negative) is unnecessary because no `txn` row has that shape.

## 6. No unclassified action, and no `transfer out`

**The "unclassified txn action(s)" warning does not fire.** All 16 distinct `txn.action` values are
covered by `CASH_TRADE` ∪ `PRICED_CORP_ACTION` ∪ `COST_IN_KIND` ∪ `ZERO_CASH`; running `compute()`
with warnings enabled produces nothing.

`transfer out` (with a space) has **two instances and both are in `cdp_cost_lot`**, not `txn` —
O5RU −29,090 and D05 −2,800, the 2020 CDP→FSM migration. They are handled by `CDP_TRANSFER` in
`cdp_cost()` and never reach `classify()`. **#135's hygiene item — that `ZERO_CASH` is missing
`transfer out` and fires a warning on every fold — is wrong about the live ledger.** The asymmetry
between `CDP_TRANSFER` and `ZERO_CASH` is real but inert.

`txn` action counts: `stock dividend` 261 (not 236), all `qty_signed = 0` — #135's echo finding
holds at the larger count.

## 7. A double-count found while measuring: H78

`H78` (Hongkong Land) is held **only at FSM** — it has no CDP `txn` rows — but it has a
`cdp_cost_lot` entry for the same trade:

```
txn 89        2020-07-30  FSM  buy   1000 @3.78  gross −3792.32
cdp_cost_lot  2020-07-30  H78  open market  1000 @3.77  amount −3792.32
```

`cdp_cost()` attaches by ticker to `("cash", sid)` whenever that position exists
(`performance.py:322-330`) — it does not check that the position contains CDP rows. So the FSM buy
is counted by `_apply_txn` **and** the identical CDP lot is added on top. The 2023-01-16 sell is
duplicated the same way.

Measured: `invested_native` **7,584.64** = 2 × 3,792.32; `avg_cost` 3.7923 against a real 3.78;
proceeds 9,776.20 = 2 × 4,888.10. Reported `pl_sgd` **2,691.56** against a true **1,595.78** —
**overstated by 1,095.78 SGD**, visible on Holdings, Performance and Overview.

H78 is the only instance: it is the sole ticker with cost lots and no CDP `txn` rows.

## 8. `cost_known` is false on six positions, not zero

#135 predicted `cost_known` would be **true for all 70** once the three free names were annotated.
Live it is **false on six**, and only one of them is a refusal:

| position | why false | is it a refusal? |
|---|---|---|
| ASTREA6B cash | genuinely no cost recorded | **yes** — the whole refusal set |
| AAPL cash | free (gift), annotation pending | no — hero with no percentage (#136) |
| HMN cash | free (dividend), annotation pending | no — hero with no percentage (#136) |
| AMZN cash | free (gift), mechanical | no — hero with no percentage (#136) |
| C31 cash | **emptied predecessor** — cost carried to 9CI | no |
| 0P00006FYT cpf | **emptied predecessor** — cost carried to 0P0001OOJG | no |

The last two are a category #135 did not anticipate. `_carry_corporate_actions` zeroes the
predecessor's `invested`, `buy_cost`, `buy_qty` and `proceeds` (`performance.py:195-197`), so a
carried-from position reads `invested = 0` → `cost_known = False` → `pl_sgd = None` while its
partition is a clean `costed`. **A husk is not a refusal**, and any rule deriving the verdict from
`cost_known` alone would refuse two positions that have nothing to refuse. Deriving from the counts,
as #135 specifies, gets them right — this is evidence *for* the counts, not against them.

Both are dropped from `/api/positions` for the same reason ASTREA6B is, so they render nowhere
today; they matter only to the contract in #131.
