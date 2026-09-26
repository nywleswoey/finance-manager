"""What the fold's rows must say of ANY book — one suite, run over every book there is.

These are the claims that do not depend on which ledger is loaded: the cost partition sums, the
cost-basis family answers together, Net is the sum of the components it ships beside, a
whole-ticker figure agrees across the ticker's legs, a group's two members and its unsplit part
tie to its stock P/L. A point-in-time reading of one ledger (a total, a set of names, a measured
peak) is not one of them and does not belong here.

They lived in tests/test_performance_live.py, which reads the APP database, so they ran on the
one machine holding the book and skipped everywhere else — CI included, where the Postgres
service exists but the app database has no schema. Each book mixes this class in and says where
its rows come from:

  - tests/test_performance_live.py — the live ledger (`pytest -m pg`, local only);
  - tests/test_fold_invariants.py  — a fabricated multi-leg ledger through `fold_positions`, and
    the committed `/api/positions?closed=true` fixture the Playwright suite serves. Both run in
    the default suite, so both run in CI.

A subclass sets, in `setUpClass`:

    rows    — the fold's rows (`compute()` / `fold_positions()` output, or a capture of it)
    traded  — tickers with realised options P/L, or None when the book cannot say (that one
              test then skips and names why)

Not collected by itself: the file name does not match `test_*.py` and the class is not a
TestCase.
"""
from portfolio.performance import is_emptied_predecessor, is_leg, rollup


class FoldInvariants:
    rows: list[dict]
    traded: set[str] | None = None

    # -- the cost partition (#148) --------------------------------------------------------

    def test_the_partition_sums_to_units_in_on_every_position(self):
        """`cost_partition`'s own self-check only logs, so without this a mis-assignment
        ships."""
        for r in self.rows:
            p = r["cost_partition"]
            self.assertAlmostEqual(p["costed"] + p["free"] + p["unknown"], p["units_in"], 4,
                                   f"{r['bucket']}/{r['ticker']}: {p}")

    def test_unknown_pct_agrees_with_the_counts_it_summarises(self):
        for r in self.rows:
            p = r["cost_partition"]
            want = round(p["unknown"] / p["units_in"], 4) if p["units_in"] else 0.0
            self.assertEqual(p["unknown_pct"], want, f"{r['bucket']}/{r['ticker']}: {p}")

    def test_cost_known_is_false_exactly_where_every_entering_unit_is_unknown(self):
        for r in self.rows:
            p = r["cost_partition"]
            all_unknown = p["units_in"] > 0 and p["unknown"] == p["units_in"]
            self.assertEqual(r["cost_known"], not all_unknown and p["units_in"] > 0,
                             f"{r['bucket']}/{r['ticker']}: {p}")

    def test_uncosted_units_is_gone_and_invested_sgd_is_null_where_cost_is_unknown(self):
        for r in self.rows:
            self.assertNotIn("uncosted_units", r)
            if not r["cost_known"]:
                self.assertIsNone(r["invested_sgd"], r["ticker"])

    # -- the four cell states (#149) ------------------------------------------------------

    def test_the_options_stream_is_absent_exactly_where_no_options_were_traded(self):
        """An optioned name may legitimately ship `0.0` — the stream exists and measured zero —
        so the rule is about ABSENCE, not about the value."""
        if self.traded is None:
            self.skipTest("this book does not say which names traded options")
        for r in self.rows:
            want = r["bucket"] == "cash" and r["ticker"] in self.traded
            self.assertEqual(r["options_pl_sgd"] is not None, want,
                             f"{r['bucket']}/{r['ticker']}: {r['options_pl_sgd']!r}")

    def test_a_closed_leg_ships_measured_zeros_not_nulls(self):
        """This is the one that decides whether a bucket column adds up: every leg that sold
        out but priced every unit it ever held knows its basis is zero."""
        for r in self.rows:
            if r["units"] > 1e-6 or not r["cost_known"] or r["cost_partition"]["unknown"]:
                continue
            for f in ("cost_basis_native", "cost_basis_sgd", "unrealised_pl_sgd"):
                self.assertEqual(r[f], 0.0, f"{r['bucket']}/{r['ticker']}.{f}")

    def test_the_cost_basis_family_answers_together_or_not_at_all(self):
        """`avg_cost: null` beside `cost_basis: 0.0` would be one leg saying both "not known"
        and "measured zero" of the same fact — which is what an emptied predecessor (C31,
        0P00006FYT) used to do."""
        for r in self.rows:
            answered = {f: r[f] is not None for f in
                        ("avg_cost", "cost_basis_native", "cost_basis_sgd")}
            self.assertEqual(len(set(answered.values())), 1, f"{r['ticker']}: {answered}")

    def test_a_leg_holding_unknown_units_nulls_the_whole_cost_basis_family(self):
        """An average over a partly-priced lot is not a price, so every field derived from one
        goes null together — never some of them."""
        for r in self.rows:
            family = ("avg_cost", "cost_basis_native", "cost_basis_sgd",
                      "realised_pl_sgd", "unrealised_pl_sgd")
            if r["cost_known"] and not r["cost_partition"]["unknown"]:
                continue
            self.assertEqual([r[f] for f in family], [None] * len(family),
                             f"{r['bucket']}/{r['ticker']}")

    def test_stock_pl_is_on_every_row_and_is_the_pair_wherever_the_pair_is_known(self):
        """`realised + unrealised ≡ proceeds − buy_cost + mv`, so the pair's sum survives a
        split nobody can make — which is what lets a caveat show an exact Net."""
        for r in self.rows:
            self.assertIn("stock_pl_sgd", r)
            # null only on a leg whose every unit is unknown AND whose name refuses: a leg like
            # that beside real cost elsewhere is a caveat's, and a caveat's Net stands (#150).
            self.assertEqual(r["stock_pl_sgd"] is None,
                             not r["cost_known"] and r["net_verdict"] == "refuse", r["ticker"])
            if r["realised_pl_sgd"] is not None and r["unrealised_pl_sgd"] is not None:
                # exactly, with no tolerance: the field is rounded FROM the members, so §14's
                # measured cent (UD1U, 00468, 01310, 01523, 00101 — `_build_row` rounding each
                # component at 2dp) stays where it already is and does not open a second gap
                # between this field and the two it is the sum of.
                self.assertEqual(round(r["realised_pl_sgd"] + r["unrealised_pl_sgd"], 2),
                                 r["stock_pl_sgd"], f"{r['bucket']}/{r['ticker']}")

    def test_the_caveat_legs_keep_their_stock_pl_out_of_the_pair(self):
        """The names the partition doubts: their components are `not known` and their Net is
        exact — the whole reason the pair ships as a sum as well as as two members. Derived
        from the partition rather than from a list of names, because the claim is about every
        doubted leg, not about which legs one ledger happens to doubt."""
        caveat = {r["ticker"]: r for r in self.rows
                  if r["cost_known"] and r["cost_partition"]["unknown"] > 0}
        self.assertTrue(caveat, "no doubted leg in this book — nothing to assert")
        for t, r in caveat.items():
            self.assertIsNone(r["realised_pl_sgd"], t)
            self.assertIsNone(r["unrealised_pl_sgd"], t)
            self.assertIsNotNone(r["stock_pl_sgd"], t)
            self.assertIsNotNone(r["pl_sgd"], t)          # the Net is still exact

    def test_every_group_ties_its_two_members_and_its_unsplit_to_its_stock_pl(self):
        """`Σ group net` must not move because four legs stopped splitting their stock P/L. The
        group carries the whole sum and names the part neither member reached, so what a page
        prints beside Net adds up to it — which is the claim a reader can check."""
        for by in ("market", "bucket", "account"):
            for k, v in rollup(self.rows, by).items():
                self.assertAlmostEqual(v["realised_pl_sgd"] + v["unrealised_pl_sgd"]
                                       + v["unsplit_pl_sgd"], v["stock_pl_sgd"],
                                       delta=0.01, msg=f"{by}/{k}")

    # -- peak capital-at-risk and the return (#143 §9) ------------------------------------

    def test_peak_car_ships_as_a_measured_zero_and_the_verdict_gates_the_render(self):
        """The field is never null, so nothing downstream can mistake "no capital was ever at
        risk" for "nobody computed it"."""
        for r in self.rows:
            self.assertIsNotNone(r["peak_car_sgd"], r["ticker"])
            self.assertIn(r["return_verdict"], ("ok", "caveat", "no_capital"), r["ticker"])
            if r["return_verdict"] == "no_capital":
                self.assertEqual(r["peak_car_sgd"], 0.0, r["ticker"])
                self.assertIsNone(r["return_pct"], r["ticker"])

    def test_the_percentage_is_net_over_peak_car_on_every_ticker(self):
        """The one arithmetic claim the hero makes. Summed across a ticker's legs, because the
        figure is whole-ticker: on the one name held in three buckets a per-leg reading is a
        different number entirely (3.9% against 31.2%)."""
        by_ticker = {}
        for r in self.rows:
            by_ticker.setdefault(r["ticker"], []).append(r)
        for ticker, rs in by_ticker.items():
            r = rs[0]
            if r["return_pct"] is None:
                continue
            # the Net that ships, and no second sum of components beside it (#150): exactly,
            # because the numerator IS this sum.
            net = round(sum(x["net_pl_sgd"] for x in rs), 2)
            self.assertEqual(r["return_pct"], round(net / r["peak_car_sgd"], 4), ticker)

    def test_the_return_fields_agree_across_every_leg_of_a_ticker(self):
        """They are whole-ticker figures riding on per-leg rows, so a consumer holding any one
        leg has the whole-ticker answer — and the four must never disagree between legs."""
        seen = {}
        for r in self.rows:
            got = {k: r[k] for k in ("peak_car_sgd", "return_span_days", "return_pct",
                                     "return_verdict", "ticker_xirr")}
            self.assertEqual(seen.setdefault(r["ticker"], got), got, r["ticker"])

    def test_a_name_listed_in_one_bucket_pools_to_that_buckets_own_xirr(self):
        """The pooled XIRR is the leg's own where there is nothing to pool: one listed leg's
        flows solved once are the same flows its `xirr` solved."""
        legs = {}
        for r in self.rows:
            if is_leg(r):
                legs.setdefault(r["ticker"], []).append(r)
        for ticker, rs in legs.items():
            if len(rs) == 1:
                self.assertEqual(rs[0]["ticker_xirr"], rs[0]["xirr"], ticker)

    # -- two verdicts on two axes, and Net on the wire (#150) -----------------------------

    def test_both_verdicts_ship_on_every_row_and_agree_across_a_tickers_legs(self):
        """Two enums, never one: a name can be hero-on-Net and no-capital-on-return at once,
        and both are whole-ticker readings riding every leg."""
        seen = {}
        for r in self.rows:
            self.assertIn(r["net_verdict"], ("hero", "caveat", "refuse", "bounded"),
                          r["ticker"])
            self.assertIn(r["return_verdict"], ("ok", "caveat", "no_capital"), r["ticker"])
            self.assertEqual(seen.setdefault(r["ticker"], r["net_verdict"]), r["net_verdict"],
                             r["ticker"])

    def test_net_verdict_reads_the_tickers_summed_counts(self):
        """The rule restated over the partitions, not over `cost_known`, with the one input
        that is not a count: a split carry's bound overrides anything but a refusal (#151)."""
        counts = {}
        for r in self.rows:
            c = counts.setdefault(r["ticker"], [0.0, 0.0, r["net_verdict"], r["provenance"]])
            c[0] += r["cost_partition"]["costed"]
            c[1] += r["cost_partition"]["unknown"]
        for ticker, (costed, unknown, verdict, prov) in counts.items():
            want = "hero" if unknown <= 1e-6 else "caveat" if costed > 1e-6 else "refuse"
            if prov and prov["bound"] and want != "refuse":
                want = "bounded"
            self.assertEqual(verdict, want, ticker)

    def test_net_is_the_sum_of_the_components_as_shipped_with_zero_tolerance(self):
        """On every position: to the cent, not within one. The measured cent §14 found lives
        between `pl_sgd` and the components, and `net_pl_sgd` follows the components — so on
        this definition it stops existing between pages."""
        for r in self.rows:
            where = f"{r['bucket']}/{r['ticker']}"
            if r["net_verdict"] == "refuse":
                self.assertIsNone(r["net_pl_sgd"], where)
                continue
            if r["realised_pl_sgd"] is not None and r["unrealised_pl_sgd"] is not None:
                stock = r["realised_pl_sgd"] + r["unrealised_pl_sgd"]
            else:
                stock = r["stock_pl_sgd"]
            self.assertEqual(r["net_pl_sgd"],
                             round(stock + r["income_sgd"] + (r["options_pl_sgd"] or 0.0), 2),
                             where)

    # -- the dated carry, `bounded`, and provenance (#151) ---------------------------------

    def test_a_split_carry_is_one_lower_bound_and_its_siblings_upper(self):
        """The cost of one event went to exactly one of its successors, and every successor
        names the reachable others."""
        by_event = {}
        for r in self.rows:
            p = r["provenance"]
            if p and p["bound"]:
                by_event.setdefault(p["from_ticker"], {})[r["ticker"]] = p
        for frm, succ in by_event.items():
            self.assertEqual(sorted(p["bound"] for p in succ.values()).count("lower"), 1, frm)
            for tk, p in succ.items():
                self.assertEqual({s["ticker"] for s in p["split_with"]}, set(succ) - {tk}, tk)
                self.assertEqual(p["carried_sgd"] > 0, p["bound"] == "lower", tk)

    def test_no_emptied_predecessor_is_leg(self):
        """Every predecessor a carry emptied fails the listing rule, which is what Holdings'
        absence rests on (#143 §13) — and `/api/holding` agrees it is a husk."""
        preds = {r["provenance"]["from_ticker"] for r in self.rows
                 if r["provenance"] and r["provenance"]["carried_sgd"] > 0}
        if not preds:
            self.skipTest("no carry fired in this book — nothing to assert")
        for r in self.rows:
            if r["ticker"] in preds:
                self.assertFalse(is_leg(r), f"{r['bucket']}/{r['ticker']}")
                self.assertTrue(is_emptied_predecessor(r, self.rows), r["ticker"])
            elif not is_leg(r):
                self.assertFalse(is_emptied_predecessor(r, self.rows), r["ticker"])
