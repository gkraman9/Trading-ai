"""Independent invented OHLC and labeled lifecycle controls, never broker data."""

from copy import deepcopy
from dataclasses import replace, asdict
from datetime import datetime, timedelta, timezone
import csv, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.market_view import build_market_view_v3
from iat.intelligence.sr_rejection import (
    evaluate_sr_rejection,
    validate_sr_result,
    SRRejectionLedger,
    validate_sr_log,
    setup_id,
    seal,
    STRATEGY,
    RULE,
)
from iat.sr_rejection_dataset import replay_sr_rejection, run_sr_manifest
from iat.intelligence.strategy_replay import digest

START = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
CONFIG = ContextConfig()
INTELLIGENCE = IntelligenceConfig(left_strength=1, right_strength=1)
SYMBOL = "SYNTHETIC_SR"


def fixture(mirror=False, tail=8):
    """Separate M1/M5 synthetic feeds for predicate tests; no cross-feed claim."""
    wave = [100.5, 101, 100.5, 100] * 5

    def bars(prices, step, begin):
        return [
            dict(
                timestamp=(begin + timedelta(minutes=n * step)).isoformat(),
                open=p,
                high=p + 0.1,
                low=p - 0.1,
                close=p,
            )
            for n, p in enumerate(prices)
        ]

    one = bars(wave, 1, START)
    one += [
        dict(
            timestamp=(START + timedelta(minutes=20)).isoformat(),
            open=100.5,
            high=100.7,
            low=100.3,
            close=100.5,
        ),
        dict(
            timestamp=(START + timedelta(minutes=21)).isoformat(),
            open=100.05,
            high=100.1,
            low=99.88,
            close=99.9,
        ),
        dict(
            timestamp=(START + timedelta(minutes=22)).isoformat(),
            open=100.05,
            high=100.5,
            low=100.0,
            close=100.3,
        ),
    ]
    one += bars([100.4] * tail, 1, START + timedelta(minutes=23))
    five = bars(wave * 2, 5, START - timedelta(minutes=80))
    if mirror:
        for row in one + five:
            o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
            row.update(open=200 - o, high=200 - l, low=200 - h, close=200 - c)
    return one, five


def snapshot(
    one=None,
    five=None,
    n=23,
    *,
    mirror=False,
    config=CONFIG,
    intelligence_config=INTELLIGENCE,
    **options
):
    if one is None:
        one, five = fixture(mirror)
    context = context_at(
        SYMBOL,
        one,
        five,
        START + timedelta(minutes=n),
        config=config,
        intelligence_config=intelligence_config,
        **options
    )
    inputs = (
        dict(
            session_snapshot=options["calendar"].public_state(
                START + timedelta(minutes=n)
            )
        )
        if options.get("calendar")
        else {}
    )
    view = build_market_view_v3(context, **inputs)
    return view, context, inputs


def result(*args, **kwargs):
    v, c, inputs = snapshot(*args, **kwargs)
    return evaluate_sr_rejection(v, c, view_inputs=inputs)


def qualified(r):
    return [e for e in r["evaluations"] if e["state"] == "QUALIFIED"]


def control_opposition(r):
    from iat.intelligence.context_evidence import identity

    key = identity(
        SYMBOL,
        "M1",
        "TRANSITION",
        "LABELED_SYNTHETIC_LIFECYCLE_CONTROL",
        r["evaluation_at_utc"],
    )
    r["evidence"][key] = dict(
        kind="CONTEXT_TRANSITION",
        timeframe="M1",
        observed_at=r["current_bar"]["opened_at"],
        available_at=r["evaluation_at_utc"],
    )
    return key


def lifecycle_control(r, *, opposing=False):
    """Labeled observation-contract control ONLY; not an OHLC-derived result.

    Exercises reducer semantics separately from source-bound end-to-end tests.
    """
    r = deepcopy(r)
    if opposing:
        key = control_opposition(r)
        for row in r["evaluations"]:
            if row["state"] == "QUALIFIED":
                row.update(
                    state="INVALIDATED",
                    contradictory_evidence=[key],
                    reason_codes=["FRESH_OPPOSING_M1_CHOCH"],
                )
                row["conditions"]["no_opposing_choch"] = False
                r["current_opposition"][row["direction"]] = [key]
    return seal({k: v for k, v in r.items() if k != "sha256"})


def manifest_fixture(root, mirror=False):
    """Independent synthetic CSVs; M5 explicitly INTERNAL AGGREGATION ONLY."""
    from hashlib import sha256

    a, b = fixture(mirror)
    a = a[:30]
    parents = []
    for row in b:
        if datetime.fromisoformat(row["timestamp"]) >= START:
            break
        parents += [
            dict(
                row,
                timestamp=(
                    datetime.fromisoformat(row["timestamp"]) + timedelta(minutes=i)
                ).isoformat(),
            )
            for i in range(5)
        ]
    a = parents + a
    b = []
    for n in range(0, len(a), 5):
        cs = a[n : n + 5]
        b.append(
            dict(
                timestamp=cs[0]["timestamp"],
                open=cs[0]["open"],
                high=max(c["high"] for c in cs),
                low=min(c["low"] for c in cs),
                close=cs[-1]["close"],
            )
        )
    frames = {}
    for tf, rows in (("M1", a), ("M5", b)):
        path = root / (tf.lower() + ".csv")
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["timestamp", "open", "high", "low", "close"],
                lineterminator="\n",
            )
            w.writeheader()
            w.writerows(rows)
        frames[tf] = dict(file=path.name, sha256=sha256(path.read_bytes()).hexdigest())
    end = (START + timedelta(minutes=30)).isoformat()
    boundary = (START + timedelta(minutes=25)).isoformat()
    manifest = dict(
        version=2,
        symbol="XAUUSD",
        dataset_kind="SYNTHETIC_FIXTURE",
        source=dict(
            name="SYNTHETIC SR fixture",
            reference="synthetic:sr-independent-unit",
            curation_id="synthetic-sr",
            retrieved_at_utc="2026-11-14T00:00:00Z",
            independent_review="PENDING",
        ),
        utc_range=dict(start=a[0]["timestamp"], end=end),
        frames=frames,
        calendar=None,
        finality_attested=True,
        evaluation=dict(start=boundary, end=end),
        warmup={
            tf: dict(start=rows[0]["timestamp"], end=boundary)
            for tf, rows in (("M1", a), ("M5", b))
        },
        lineage=dict(
            feed_id="SYNTHETIC_ONLY",
            price_basis="BID",
            timestamp_convention="INTERVAL_OPEN_UTC",
            m5_origin="AGGREGATED_FROM_M1",
            raw_sha256=digest(a),
        ),
        evidence_review={
            k: dict(
                status="PENDING",
                reference="synthetic:sr-unit-only",
                reason_code="SYNTHETIC_ONLY",
            )
            for k in (
                "usage",
                "instrument",
                "timestamp",
                "price_basis",
                "calendar",
                "finality",
            )
        },
    )
    path = root / "manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return path


class SRPredicateTests(unittest.TestCase):
    def safe(self, r, **inputs):
        self.assertTrue(validate_sr_result(r, **inputs))
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)
        self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
        self.assertEqual(r["exness"], "BLOCKED")
        self.assertEqual(r["historical_validation"], "PENDING")
        self.assertEqual(r["historical_comparisons"], "NOT_RUN")
        self.assertEqual(r["validation_status"], "SYNTHETIC_ONLY")
        return r

    def test_bullish_and_bearish_qualify_from_independent_ohlc(self):
        for mirror in (False, True):
            v, c, inputs = snapshot(mirror=mirror)
            r = self.safe(
                evaluate_sr_rejection(v, c, view_inputs=inputs),
                view=v,
                context=c,
                view_inputs=inputs,
            )
            self.assertTrue(qualified(r))
            self.assertTrue(
                all(
                    e["direction"] == ("BEARISH" if mirror else "BULLISH")
                    for e in qualified(r)
                )
            )
            for e in qualified(r):
                self.assertTrue(all(e["conditions"].values()))
                self.assertIsNotNone(e["candles"]["C"])

    def test_touch_is_candidate_not_qualified(self):
        r = self.safe(result(n=22))
        self.assertFalse(qualified(r))
        self.assertTrue(
            any(
                e["state"] == "CANDIDATE" and e["candles"]["C"] is None
                for e in r["evaluations"]
            )
        )

    def test_missing_confirmation_body_abstains(self):
        a, b = fixture()
        a[22].update(open=100.4, close=100.3)
        r = self.safe(result(a, b))
        self.assertFalse(qualified(r))
        self.assertTrue(
            any(
                "M1_CONFIRMATION_NOT_DIRECTIONAL" in e["reason_codes"]
                for e in r["evaluations"]
            )
        )

    def test_confirmation_boundary_strictly_exceeds_existing_tolerance(self):
        a, b = fixture()
        a[22].update(open=99.95, close=99.96, low=99.94)
        r = self.safe(result(a, b))
        self.assertFalse(qualified(r))
        self.assertTrue(
            any(
                "CONFIRMATION_BOUNDARY_NOT_CLEARED" in e["reason_codes"]
                for e in r["evaluations"]
            )
        )

    def test_wrong_m5_structure_abstains(self):
        a, b = fixture()
        for i, row in enumerate(b):
            v = 105 - i * 0.2 + (1 if i % 4 == 1 else -1 if i % 4 == 3 else 0)
            row.update(open=v, high=v + 0.1, low=v - 0.1, close=v)
        r = self.safe(result(a, b))
        self.assertFalse(qualified(r))
        self.assertTrue(
            any(
                "M5_STRUCTURE_INCOMPATIBLE" in e["reason_codes"]
                for e in r["evaluations"]
            )
        )

    def test_unsupported_zone_lifecycle_never_qualifies(self):
        a, b = fixture()
        a[19].update(open=99.7, high=100.1, low=99.5, close=99.6)
        r = self.safe(result(a, b))
        self.assertFalse([e for e in qualified(r) if e["zone"]["timeframe"] == "M1"])
        self.assertTrue(
            any("UNSUPPORTED_ZONE_STATE" in e["reason_codes"] for e in r["evaluations"])
        )

    def test_overlapping_zones_remain_distinct(self):
        r = self.safe(result())
        q = qualified(r)
        self.assertGreaterEqual(len(q), 2)
        self.assertEqual(len({e["setup_id"] for e in q}), len(q))
        self.assertEqual(len({e["zone"]["id"] for e in q}), len(q))

    def test_zone_knowledge_condition_is_causal(self):
        # Genuine new M1 zone formed only when C confirms the T pivot.
        a, b = fixture()
        for n in (7, 11, 15, 19):
            a[n].update(open=100.2, high=100.3, low=100.1, close=100.2)
        observed = self.safe(result(a, b))
        late = [
            e
            for e in observed["evaluations"]
            if e["zone"]["timeframe"] == "M1" and not e["conditions"]["zone_known"]
        ]
        self.assertTrue(late)
        self.assertTrue(all(e["state"] != "QUALIFIED" for e in late))
        r = self.safe(result())
        for e in qualified(r):
            self.assertLessEqual(
                datetime.fromisoformat(e["zone"]["confirmed_at"]),
                datetime.fromisoformat(r["evidence"][e["candles"]["T"]]["observed_at"]),
            )
        # A fully rechecksummed typed context with a forged late zone is rejected
        # by the inherited source-bound view path, never used to qualify.
        v, c, inputs = snapshot()
        raw = deepcopy(c.interpretations)
        z = raw["frames"]["M1"]["support_resistance"][0]
        raw["frames"]["M1"]["support_resistance"] = (
            replace(z, confirmed_at=c.analysis_at),
        ) + tuple(raw["frames"]["M1"]["support_resistance"][1:])
        bad = replace(c, interpretations=raw)
        self.assertEqual(evaluate_sr_rejection(v, bad)["status"], "BLOCKED")

    def test_missing_stale_and_unfinished_data_block(self):
        a, b = fixture()
        for one, five, n in ((None, b, 23), (a, None, 23), (a[:23], b[:20], 90)):
            self.assertEqual(
                self.safe(
                    result(one, five, n=n) if one is not None else self._missing(a, b)
                )["status"],
                "BLOCKED",
            )
        c = context_at(
            SYMBOL,
            a,
            b,
            START + timedelta(minutes=23),
            config=CONFIG,
            intelligence_config=INTELLIGENCE,
        )
        # Direct context entry rejects an unclosed M5; causal prefix path excludes it.
        from iat.intelligence.context import analyze_context

        five = [
            r
            for r in b
            if datetime.fromisoformat(r["timestamp"]) <= START + timedelta(minutes=20)
        ]
        bad = analyze_context(
            SYMBOL,
            a[:23],
            five,
            START + timedelta(minutes=23),
            config=CONFIG,
            intelligence_config=INTELLIGENCE,
        )
        self.assertEqual(
            self.safe(evaluate_sr_rejection(build_market_view_v3(bad), bad))["status"],
            "BLOCKED",
        )

    def _missing(self, a, b):
        c = context_at(
            SYMBOL,
            None,
            b,
            START + timedelta(minutes=23),
            config=CONFIG,
            intelligence_config=INTELLIGENCE,
        )
        return evaluate_sr_rejection(build_market_view_v3(c), c)

    def test_unknown_session_explicit_and_blocked_calendar_not_bypassed(self):
        r = self.safe(result())
        self.assertIn("SESSION_SNAPSHOT_UNAVAILABLE", r["restrictions"]["reason_codes"])
        from iat.session_config import compile_session_config

        cal = json.loads(
            Path("config/profiles/exness-xauusd-v2.candidate.json").read_text()
        )
        cal["symbol"] = (
            SYMBOL  # in-memory synthetic mismatch control; never written/approved
        )
        v, c, inputs = snapshot(
            calendar=compile_session_config(cal), observed_finality=True
        )
        self.assertEqual(
            self.safe(evaluate_sr_rejection(v, c, view_inputs=inputs))["status"],
            "BLOCKED",
        )

    def test_wrong_view_configuration_or_source_blocks(self):
        v, c, _ = snapshot()
        other, _, _ = snapshot(mirror=True)
        self.assertEqual(
            self.safe(evaluate_sr_rejection(other, c))["status"], "BLOCKED"
        )
        bad = replace(c, configuration_sha256="0" * 64)
        self.assertEqual(self.safe(evaluate_sr_rejection(v, bad))["status"], "BLOCKED")

    def test_historical_label_alone_never_qualifies(self):
        v, c, _ = snapshot(provenance="HISTORICAL_RESEARCH")
        r = self.safe(evaluate_sr_rejection(v, c))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("HISTORICAL_MANIFEST_REQUIRED", r["reason_codes"])

    def test_malformed_inputs_fail_closed(self):
        for c in (None, {}, object()):
            self.assertEqual(
                self.safe(evaluate_sr_rejection(None, c))["status"], "BLOCKED"
            )
        v, c, _ = snapshot()
        self.assertEqual(
            self.safe(evaluate_sr_rejection(v, replace(c, symbol=object())))["status"],
            "BLOCKED",
        )

    def test_stable_setup_ids_and_no_upstream_mutation(self):
        v, c, _ = snapshot()
        before = (deepcopy(v), deepcopy(c.to_dict()))
        first = evaluate_sr_rejection(v, c)
        second = evaluate_sr_rejection(v, c)
        self.assertEqual(first, second)
        self.assertEqual(before, (v, c.to_dict()))
        for row in first["evaluations"]:
            self.assertEqual(
                row["setup_id"],
                setup_id(
                    SYMBOL, row["direction"], row["zone"]["id"], row["candles"]["T"]
                ),
            )

    def test_result_schema_and_source_bound_tampering(self):
        v, c, _ = snapshot()
        r = self.safe(evaluate_sr_rejection(v, c))
        for change in (
            {"signal": "BUY"},
            {"execution_allowed": True},
            {"qualification": "DATA_QUALIFIED"},
            {"order_request": {}},
        ):
            bad = seal(dict({k: v for k, v in r.items() if k != "sha256"}, **change))
            with self.assertRaises((ValueError, ValidationError)):
                validate_sr_result(bad)
        bad = deepcopy(r)
        bad["evaluations"][0]["zone"]["upper"] += 1
        bad = seal({k: v for k, v in bad.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_sr_result(bad, view=v, context=c)

    def test_exit_hypothesis_has_no_execution_prices_or_pnl(self):
        r = self.safe(result())

        def scan(x):
            if isinstance(x, dict):
                self.assertFalse(
                    {
                        "entry_price",
                        "stop_loss",
                        "take_profit",
                        "position_size",
                        "profit",
                        "pnl",
                        "order_request",
                    }
                    & set(x)
                )
                for v in x.values():
                    scan(v)
            elif isinstance(x, list):
                for v in x:
                    scan(v)

        scan(r)


class SRLifecycleTests(unittest.TestCase):
    def record(self, ledger, n, *, a=None, b=None, mirror=False):
        v, c, inputs = snapshot(a, b, n=n, mirror=mirror)
        return ledger.record(v, c, view_inputs=inputs)

    def test_candidate_then_qualified_and_duplicate_observation_once(self):
        ledger = SRRejectionLedger()
        self.record(ledger, 22)
        e = self.record(ledger, 23)
        before = ledger.to_dict()
        self.assertEqual(self.record(ledger, 23), e)
        self.assertEqual(before, ledger.to_dict())
        self.assertEqual(
            before["summary"]["directions"]["BULLISH"]["unique_qualified"], 2
        )
        validate_sr_log(before)

    def test_five_eligible_closes_expire_both_directions(self):
        for mirror in (False, True):
            l = SRRejectionLedger()
            self.record(l, 22, mirror=mirror)
            self.record(l, 23, mirror=mirror)
            for n in range(24, 28):
                self.record(l, n, mirror=mirror)
            group = "BEARISH" if mirror else "BULLISH"
            self.assertEqual(
                l.to_dict()["summary"]["directions"][group]["expired_qualified"], 0
            )
            self.record(l, 28, mirror=mirror)
            log = l.to_dict()
            self.assertEqual(
                log["summary"]["directions"][group]["expired_qualified"], 2
            )
            validate_sr_log(log)

    def test_invalidation_after_qualification(self):
        for mirror in (False, True):
            a, b = fixture(mirror)
            l = SRRejectionLedger()
            self.record(l, 22, a=a, b=b)
            self.record(l, 23, a=a, b=b)
            a[23].update(
                open=100,
                high=101 if mirror else 100.1,
                low=99.9 if mirror else 99.4,
                close=100.5 if mirror else 99.5,
            )
            self.record(l, 24, a=a, b=b)
            d = "BEARISH" if mirror else "BULLISH"
            self.assertEqual(
                l.to_dict()["summary"]["directions"][d]["invalidated_qualified"], 2
            )
            validate_sr_log(l.to_dict())

    def test_unqualified_invalidation_never_counts_as_invalidated_qualified(self):
        control = lifecycle_control(result(), opposing=True)
        validate_sr_result(control)
        l = SRRejectionLedger()
        l._record(control)
        g = l.to_dict()["summary"]["directions"]["BULLISH"]
        self.assertEqual(g["unique_qualified"], 0)
        self.assertEqual(g["invalidated_qualified"], 0)
        self.assertEqual(g["unqualified_invalidated"], 2)
        validate_sr_log(l.to_dict())

    def test_opposing_change_invalidates_qualified_without_new_touch(self):
        l = SRRejectionLedger()
        l._record(result(n=23))
        r = result(n=24)
        key = control_opposition(r)
        r["current_opposition"]["BULLISH"] = [key]
        r = seal({k: v for k, v in r.items() if k != "sha256"})
        l._record(r)
        self.assertEqual(
            l.to_dict()["summary"]["directions"]["BULLISH"]["invalidated_qualified"], 2
        )

    def test_blocked_observation_does_not_advance_expiry(self):
        l = SRRejectionLedger()
        self.record(l, 22)
        self.record(l, 23)
        v, c, _ = snapshot(n=24)
        bad = deepcopy(v)
        bad["sha256"] = "0" * 64
        l.record(bad, c)
        self.assertEqual(l.to_dict()["summary"]["blocked_snapshots"], 1)
        for n in range(25, 29):
            self.record(l, n)
        self.assertEqual(
            l.to_dict()["summary"]["directions"]["BULLISH"]["expired_qualified"], 0
        )
        self.record(l, 29)
        self.assertEqual(
            l.to_dict()["summary"]["directions"]["BULLISH"]["expired_qualified"], 2
        )

    def test_missing_immediate_confirmation_cannot_be_backfilled(self):
        l = SRRejectionLedger()
        self.record(l, 22)
        v, c, _ = snapshot(n=23)
        bad = deepcopy(v)
        bad["sha256"] = "0" * 64
        l.record(bad, c)
        self.record(l, 24)
        self.assertEqual(
            l.to_dict()["summary"]["directions"]["BULLISH"]["unique_qualified"], 0
        )
        self.assertTrue(
            any(t["to_state"] == "ABSTAINED" for t in l.entries[-1]["transitions"])
        )

    def test_new_touch_episode_rearms_distinct_ids(self):
        a, b = fixture()
        a[24].update(open=100.05, high=100.1, low=99.88, close=99.9)
        a[25].update(open=100.05, high=100.5, low=100.0, close=100.3)
        l = SRRejectionLedger()
        for n in range(22, 27):
            self.record(l, n, a=a, b=b)
        log = l.to_dict()
        self.assertEqual(log["summary"]["directions"]["BULLISH"]["unique_qualified"], 4)
        self.assertEqual(
            len({s["setup_id"] for s in log["setups"] if s["qualified_at_utc"]}), 4
        )

    def test_same_cutoff_revision_backward_clock_and_correction_rejected_atomically(
        self,
    ):
        l = SRRejectionLedger()
        self.record(l, 23)
        before = l.to_dict()
        with self.assertRaises(ValueError):
            self.record(l, 22)
        v, c, _ = snapshot(n=23)
        bad = deepcopy(v)
        bad["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            l.record(bad, c)
        a, b = fixture()
        a[0]["close"] += 0.01
        with self.assertRaises(ValueError):
            self.record(l, 24, a=a, b=b)
        self.assertEqual(l.to_dict(), before)

    def test_log_transition_and_inventory_tampering_rejected(self):
        l = SRRejectionLedger()
        self.record(l, 22)
        self.record(l, 23)
        r = l.to_dict()
        r["summary"]["directions"]["BULLISH"]["unique_qualified"] = 99
        r = seal({k: v for k, v in r.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_sr_log(r)

    def test_paper_exit_and_expiry_same_close_is_unresolved(self):
        a, b = fixture()
        l = SRRejectionLedger()
        for n in range(22, 28):
            self.record(l, n, a=a, b=b)
        a[27].update(open=101, high=102, low=100.8, close=101.8)
        self.record(l, 28, a=a, b=b)
        done = [s for s in l.to_dict()["setups"] if s["qualified_at_utc"]]
        self.assertTrue(
            all(s["paper_review"]["status"] == "UNRESOLVED_EVENT_ORDER" for s in done)
        )

    def test_raw_replay_repeat_prefix_and_future_append(self):
        a, b = fixture(tail=6)
        options = dict(config=CONFIG, intelligence_config=INTELLIGENCE)
        full = replay_sr_rejection(SYMBOL, a, b, **options)
        self.assertEqual(full, replay_sr_rejection(SYMBOL, a, b, **options))
        validate_sr_log(full)
        cutoff = START + timedelta(minutes=24)
        smalla = [
            r
            for r in a
            if datetime.fromisoformat(r["timestamp"]) + timedelta(minutes=1) <= cutoff
        ]
        smallb = [
            r
            for r in b
            if datetime.fromisoformat(r["timestamp"]) + timedelta(minutes=5) <= cutoff
        ]
        prefix = replay_sr_rejection(SYMBOL, smalla, smallb, **options)
        self.assertEqual(full["entries"][: len(prefix["entries"])], prefix["entries"])
        a.append(
            dict(
                timestamp=(START + timedelta(minutes=len(a))).isoformat(),
                open=1,
                high=999,
                low=0.1,
                close=998,
            )
        )
        bounded = replay_sr_rejection(SYMBOL, a, b, as_of=cutoff, **options)
        self.assertEqual(prefix, bounded)

    def test_manifest_missing_input_and_checksum_rejection(self):
        self.assertEqual(run_sr_manifest()["status"], "BLOCKED")
        # Reuse only the inherited manifest writer here; not its strategy fixtures.
        from test_evaluation_window import v2_fixture

        with tempfile.TemporaryDirectory() as folder:
            p = v2_fixture(Path(folder))
            file = Path(folder) / "m1.csv"
            file.write_bytes(file.read_bytes() + b"\n")
            r = run_sr_manifest(p)
            self.assertEqual(r["status"], "BLOCKED")
            self.assertIsNone(r["replay"])

    def test_existing_registry_adaptive_candidates_and_logs_unchanged(self):
        from iat.intelligence.strategy_registry import registry
        from iat.intelligence.adaptive import assess_adaptive
        from iat.intelligence.strategies import evaluate_strategies
        from iat.intelligence.context_evidence import ReplayLedger
        from iat.intelligence.decision_log import from_replay

        v, c, _ = snapshot()
        before = (
            registry(),
            assess_adaptive(c),
            evaluate_strategies(c),
            asdict(from_replay(ReplayLedger().record(c))),
        )
        evaluate_sr_rejection(v, c)
        after = (
            registry(),
            assess_adaptive(c),
            evaluate_strategies(c),
            asdict(from_replay(ReplayLedger().record(c))),
        )
        self.assertEqual(before, after)
        self.assertEqual(len(after[0]["strategies"]), 2)
        self.assertEqual(len(after[1]["assessment"]["candidate_assessments"]), 4)

    def test_real_ohlc_opposing_wick_choch_blocks_confirmation_before_qualification(
        self,
    ):
        a, b = fixture()
        prices = [
            100.5,
            101,
            100,
            99.9,
            100.4,
            101.5,
            100.6,
            100.2,
            100.8,
            102,
            101,
            100.5,
            101,
            102.5,
            101.3,
            100.8,
            101.4,
            103,
            101.5,
            101,
        ]
        for row, price in zip(a, prices):
            row.update(open=price, high=price + 0.1, low=price - 0.1, close=price)
        a[22]["low"] = 99.7
        policy = IntelligenceConfig(
            left_strength=1, right_strength=1, break_policy="WICK"
        )
        l = SRRejectionLedger()
        for n in (22, 23):
            v, c, inputs = snapshot(a, b, n=n, intelligence_config=policy)
            l.record(v, c, view_inputs=inputs)
        log = l.to_dict()
        g = log["summary"]["directions"]["BULLISH"]
        self.assertEqual(g["unique_qualified"], 0)
        self.assertGreater(g["unqualified_invalidated"], 0)
        self.assertEqual(g["invalidated_qualified"], 0)
        self.assertTrue(
            any(
                "FRESH_OPPOSING_M1_CHOCH" in row["reason_codes"]
                for row in l.last["evaluations"]
            )
        )
        validate_sr_log(log)

    def test_late_m5_history_is_rejected_without_rewriting_prior_state(self):
        a, b = fixture()
        l = SRRejectionLedger()
        self.record(l, 23, a=a, b=b[:19])
        before = l.to_dict()
        with self.assertRaisesRegex(ValueError, "SR_LATE_OR_CORRECTED_CANDLE"):
            self.record(l, 24, a=a, b=b[:20])
        self.assertEqual(l.to_dict(), before)

    def test_full_manifest_preflight_carry_in_and_readonly_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = manifest_fixture(root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            r = run_sr_manifest(path, config=CONFIG, intelligence_config=INTELLIGENCE)
            self.assertEqual(r["status"], "WARN", r["reason_codes"])
            self.assertIsNotNone(r["replay"])
            self.assertTrue(validate_sr_log(r["replay"]))
            self.assertEqual(r["historical_validation"], "PENDING")
            self.assertIsNone(r["historical_metrics"])
            self.assertEqual(
                r["preflight"]["alignment"]["evaluation"]["consistency_evidence"],
                "INTERNAL_AGGREGATION_ONLY",
            )
            account = r["window_accounting"]
            self.assertTrue(account["carried_in_qualified_setup_ids"])
            self.assertFalse(account["evaluation_first_qualifications"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertEqual(
                r,
                run_sr_manifest(path, config=CONFIG, intelligence_config=INTELLIGENCE),
            )

    def test_unqualified_historical_manifest_cannot_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = manifest_fixture(root)
            data = json.loads(path.read_text())
            data["dataset_kind"] = "INDEPENDENT_HISTORICAL"
            data["source"][
                "reference"
            ] = "https://example.org/synthetic-unqualified-control"
            path.write_text(json.dumps(data))
            r = run_sr_manifest(path, config=CONFIG, intelligence_config=INTELLIGENCE)
            self.assertEqual(r["status"], "BLOCKED")
            self.assertIsNone(r["replay"])
            self.assertIsNone(r["historical_metrics"])
            self.assertEqual(r["historical_comparisons"], "NOT_RUN")
            self.assertIn("INDEPENDENT_REVIEW_PENDING", r["reason_codes"])

    def test_opposition_cannot_be_an_arbitrary_candle_reference(self):
        r = result()
        key = next(k for k, e in r["evidence"].items() if e["kind"] == "CANDLE")
        r["current_opposition"]["BULLISH"] = [key]
        r = seal({k: v for k, v in r.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_sr_result(r)

    def test_frozen_synthetic_examples_and_schema_are_repeatable(self):
        schema = json.loads(
            Path("config/sr-rejection-research-v1.schema.json").read_text()
        )
        Draft202012Validator.check_schema(schema)
        audit = json.loads(
            Path("docs/research_audits/sr-rejection.synthetic.json").read_text()
        )
        for name, opts in (
            ("bullish", {}),
            ("bearish", {"mirror": True}),
            ("candidate", {"n": 22}),
        ):
            self.assertEqual(
                result(**opts)["sha256"], audit["cases"][name]["snapshot_sha256"]
            )
        l = SRRejectionLedger()
        for n in range(22, 29):
            self.record(l, n)
        self.assertEqual(l.to_dict()["sha256"], audit["lifecycle_log_sha256"])
