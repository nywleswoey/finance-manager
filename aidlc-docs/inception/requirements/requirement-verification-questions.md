# Requirements Verification Questions — Net-Worth Snapshot

Fill in each `[Answer]:` tag. For multiple choice, put the letter (and detail for "Other").

---

## Q1: Snapshot history vs current-only
Do you want to keep history of net-worth over time, or just maintain one current set of values you edit in place?

A) History — each "snapshot" is dated; I can add a new snapshot periodically and see net-worth change over time
B) Current-only — one editable value per item; updating overwrites the old value (simpler)
C) Current-only now, but design so history can be added later
X) Other (describe after [Answer])

[Answer]: A

---

## Q2: Broker cash accounts vs live investment portfolio (avoid double-counting)
Items 4–8 (Tiger HKD/SGD/USD/Vault, IBKR SGD) — are these the **uninvested cash balances** at those brokers, while your stock/option **positions** come from the live portfolio (item 15)? Or do some of these numbers already include invested value?

A) They are cash balances only; invested positions are separate and pulled live (no overlap)
B) Some overlap — these figures include invested value too (I'll clarify which)
C) Tiger Vault is a money-market/cash-management balance; the other Tiger/IBKR are pure cash
X) Other (describe after [Answer])

[Answer]: A

---

## Q3: Currency of each manual item
Tiger HKD and Tiger USD imply foreign-currency balances. Do you enter these in their native currency (HKD, USD) and have the app convert to SGD using stored FX rates, or do you enter all values already in SGD?

A) Enter native currency per item; app converts to SGD using existing `fx_rate` table
B) I enter everything in SGD already
X) Other (describe after [Answer])

[Answer]: A

---

## Q4: "Liquid assets" definition
Which items count as **liquid**? (multi-select — list all letters that apply)

A) POSB shared account
B) DBS Multiplier
C) SRS account
D) Tiger HKD / SGD / USD cash
E) Tiger Vault
F) IBKR SGD cash
G) Live investment portfolio (marketable positions)
H) CPF OA / SA / MA
I) Tampines HDB

[Answer]: A, B, D, E, F

---

## Q5: Item classification for the three net-worth queries
Confirm the tagging used by the exclusion queries:

- **Housing** = Tampines HDB (asset) + CPF Home Loan (liability) + CPF Home Loan Accrued Interest (liability)
- **CPF** = CPF OA + CPF SA + CPF MA (and is CPF accrued-interest liability counted under "CPF" or under "housing"?)

A) Correct as written; accrued interest stays under Housing
B) Correct, but accrued interest should count under CPF, not Housing
C) Needs changes (describe after [Answer])

[Answer]: A

---

## Q6: CPF Home Loan Accrued Interest — is it a true liability?
Item 14 is the interest you must refund to your CPF OA when you sell the flat (because OA was used for the down-payment/instalments). Treat it as a **liability** that reduces net worth?

A) Yes — liability that reduces net worth (and reduces "net worth excl. housing" calc by being excluded with housing)
B) No — informational only, do not subtract from net worth
X) Other (describe after [Answer])

[Answer]: A

---

## Q7: How do you want to view/edit this?
A) New page/section in the existing web UI (web/) with a form to edit values + a net-worth summary panel
B) API endpoints only; I'll edit values via DB/script for now
C) Both API + UI
X) Other (describe after [Answer])

[Answer]: A

---

## Q8: Are the 14 manual items the full fixed list, or should I be able to add/remove items later?
A) Fixed list of these 14 — keep it simple
B) Generic — I can add/rename/remove asset & liability line items later
X) Other (describe after [Answer])

[Answer]: A

---

## Q9: Security Extensions
Should security extension rules be enforced for this project?

A) Yes — enforce all SECURITY rules as blocking constraints (recommended for production-grade applications)
B) No — skip all SECURITY rules (suitable for PoCs, prototypes, and experimental projects)
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Q10: Property-Based Testing Extension
Should property-based testing (PBT) rules be enforced for this project?

A) Yes — enforce all PBT rules as blocking constraints
B) Partial — enforce PBT rules only for pure functions and serialization round-trips
C) No — skip all PBT rules (suitable for simple CRUD apps, UI-only, or thin layers)
X) Other (please describe after [Answer]: tag below)

[Answer]: C
