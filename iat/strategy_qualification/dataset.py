"""Manifest/human-review gated Stage-B study. Never accepts execution approval flags."""

from copy import deepcopy
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from hashlib import sha256
from iat.pilot_qualification import qualify_historical
from iat.replay_dataset import load_dataset, strict_json, read_bytes, utc
from iat.intelligence.strategy_replay import digest
from iat.historical_replay import safety
from iat.strategy_qualification.specs import specifications, PROTOCOL, PROTOCOL_SHA256
from iat.strategy_qualification.quotes import qualify_quotes
from iat.strategy_qualification.decisions import decisions_from_candles
from iat.strategy_qualification.backtest import Costs, _simulate, dec
from iat.strategy_qualification.metrics import (
    metrics,
    qualification_status,
    QUALIFICATION_STATES,
)
from iat.strategy_qualification.validation import validation_runs, validate_plan


def run_identifier(
    manifest=None, review=None, quotes=None, costs=None, plan=None, reproductions=None
):
    values = []
    for path in (
        manifest,
        review,
        quotes,
        costs,
        plan,
        *[v for k, v in sorted((reproductions or {}).items())],
    ):
        try:
            values.append(sha256(read_bytes(path)).hexdigest() if path else None)
        except Exception:
            values.append("UNAVAILABLE")
    return digest([PROTOCOL_SHA256, values])


def empty_study():
    r = dict(
        study_version=1,
        run_id=digest(None),
        analysis_status="NOT_RUN",
        inputs=None,
        stage="B",
        status="BLOCKED",
        recommendation="BLOCKED",
        source=None,
        source_qualification=None,
        quote_qualification=None,
        specifications=[s.description() for s in specifications()],
        protocol=deepcopy(PROTOCOL),
        protocol_sha256=PROTOCOL_SHA256,
        candidates=[
            dict(
                strategy_id=s.strategy_id,
                specification_sha256=s.sha256,
                qualification="DATA_NOT_QUALIFIED",
                reason_codes=["QUALIFIED_HISTORICAL_EXPORT_REQUIRED"],
                historical_metrics=None,
                backtest=None,
                validation=None,
            )
            for s in specifications()
        ],
        qualification_states=list(QUALIFICATION_STATES),
        reason_codes=["QUALIFIED_HISTORICAL_EXPORT_REQUIRED"],
        comparisons="NOT_RUN",
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
        exness="BLOCKED",
        safety=safety(),
        later_stages={
            "C": {
                "status": "BLOCKED_NOT_STARTED",
                "reason": "NO_STAGE_B_QUALIFIED_CANDIDATE",
            },
            "D": {
                "status": "BLOCKED_NOT_STARTED",
                "reason": "STAGE_B_AND_C_ACCEPTANCE_NOT_ESTABLISHED",
            },
        },
        acceptance="NOT_ESTABLISHED",
        quote_bar_audit=None,
        data_limits=[
            "EXISTING_5000_ROW_PER_FRAME_REPLAY_LIMIT_PRESERVED",
            "LONGITUDINAL_SHARDING_NOT_YET_INDEPENDENTLY_VALIDATED",
        ],
    )
    return r


def quote_bar_audit(dataset, quotes):
    index = {}
    for q in quotes:
        t = utc(q.timestamp)
        opening = t.replace(second=0, microsecond=0)
        basis = dataset.metadata["lineage"]["price_basis"]
        v = (
            dec(q.bid)
            if basis == "BID"
            else dec(q.ask) if basis == "ASK" else (dec(q.bid) + dec(q.ask)) / 2
        )
        index.setdefault(opening, []).append(v)
    missing = mismatch = 0
    for bar in dataset.rows["M1"]:
        values = index.get(utc(bar["timestamp"]))
        if not values:
            missing += 1
            continue
        expected = dict(
            open=values[0], high=max(values), low=min(values), close=values[-1]
        )
        if any(
            abs(expected[k] - Decimal(str(bar[k]))) > Decimal(".00000001")
            for k in expected
        ):
            mismatch += 1
    return dict(
        m1_bars=len(dataset.rows["M1"]),
        missing_quote_groups=missing,
        ohlc_mismatches=mismatch,
        m5_consistency=(
            "INTERNAL_AGGREGATION_ONLY"
            if dataset.metadata["lineage"]["m5_origin"] == "AGGREGATED_FROM_M1"
            else "NATIVE_SAME_FEED_DECLARED_REVIEW_REQUIRED"
        ),
    )


def run_study(
    manifest_path=None,
    review_path=None,
    quote_manifest_path=None,
    costs_path=None,
    plan_path=None,
    reproduction_reviews=None,
):
    r = empty_study()
    r["run_id"] = run_identifier(
        manifest_path,
        review_path,
        quote_manifest_path,
        costs_path,
        plan_path,
        reproduction_reviews,
    )
    r["inputs"] = dict(
        manifest=str(Path(manifest_path).resolve()) if manifest_path else None,
        review=str(Path(review_path).resolve()) if review_path else None,
        quotes=(
            str(Path(quote_manifest_path).resolve()) if quote_manifest_path else None
        ),
        costs=str(Path(costs_path).resolve()) if costs_path else None,
        plan=str(Path(plan_path).resolve()) if plan_path else None,
        reproductions={
            k: str(Path(v).resolve()) if v else None
            for k, v in (reproduction_reviews or {}).items()
        },
    )
    q = qualify_historical(manifest_path, review_path)
    r["source_qualification"] = q
    r["source"] = q["dataset"]
    reasons = list(q["reason_codes"])
    if q["status"] != "HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED":
        reasons += [
            "QUALIFIED_BID_ASK_QUOTES_REQUIRED",
            "DATED_COST_AND_SYMBOL_EVIDENCE_REQUIRED",
            "PREDECLARED_IS_OOS_PLAN_REQUIRED",
            "INDEPENDENT_BACKTEST_REPRODUCTION_REQUIRED",
        ]
    else:
        try:
            dataset = load_dataset(manifest_path)
            if dataset.metadata != q["dataset"]:
                raise ValueError("DATASET_CHANGED_AFTER_QUALIFICATION")
            quote = qualify_quotes(quote_manifest_path, dataset)
            r["quote_qualification"] = {k: v for k, v in quote.items() if k != "quotes"}
            reasons += quote["reason_codes"]
            if costs_path is None:
                reasons.append("DATED_COST_AND_SYMBOL_EVIDENCE_REQUIRED")
            if plan_path is None:
                reasons.append("PREDECLARED_IS_OOS_PLAN_REQUIRED")
            if not reasons:
                raw = read_bytes(costs_path)
                obj = strict_json(raw)
                if set(obj) != {f.name for f in fields(Costs)}:
                    raise ValueError("COST_MODEL_INVALID")
                obj["rollovers"] = tuple(obj["rollovers"])
                costs = Costs(**obj)
                if costs.spread_stress_multiplier != "1":
                    raise ValueError("BASELINE_SPREAD_MODEL_MUST_BE_OBSERVED")
                plan = strict_json(read_bytes(plan_path))
                validate_plan(plan)
                if (
                    sha256(raw).hexdigest()
                    != quote["metadata"]["reviewed_costs_config_sha256"]
                    or costs.evidence_sha256
                    != quote["metadata"]["cost_document_sha256"]
                ):
                    raise ValueError("COST_MODEL_REVIEW_BINDING_REQUIRED")
                bounds = dataset.metadata["evaluation"]
                intervals = [plan["in_sample"], plan["out_of_sample"]] + [
                    i for f in plan["walk_forward"] for i in (f["train"], f["test"])
                ]
                if any(
                    not utc(bounds["start"])
                    <= utc(i["start"])
                    < utc(i["end"])
                    <= utc(bounds["end"])
                    for i in intervals
                ):
                    raise ValueError("VALIDATION_WINDOWS_OUTSIDE_EVALUATION")
                audit = quote_bar_audit(dataset, quote["quotes"])
                r["quote_bar_audit"] = audit
                if audit["missing_quote_groups"] or audit["ohlc_mismatches"]:
                    raise ValueError("QUOTE_BAR_ALIGNMENT_UNESTABLISHED")
                if any(
                    dec(q_.bid) % dec(costs.tick_size)
                    or dec(q_.ask) % dec(costs.tick_size)
                    for q_ in quote["quotes"]
                ):
                    raise ValueError("QUOTE_COST_TICK_SIZE_MISMATCH")
                if dataset.calendar is None or not hasattr(
                    dataset.calendar, "public_state"
                ):
                    raise ValueError("DATED_SESSION_PERMISSIONS_REQUIRED")

                def permissions(at):
                    p = dataset.calendar.public_state(at)["permissions"]
                    return dict(
                        quotes=p["market_data_expected"],
                        open=p["broker_open_positions"],
                        close=p["broker_close_positions"],
                    )

                binding = dict(
                    dataset_id=q["dataset_id"],
                    human_review_sha256=q["human_review_sha256"],
                    quote_manifest_sha256=quote["metadata"]["manifest_sha256"],
                )
                evaluation = dataset.metadata["evaluation"]
                quotes = tuple(
                    v
                    for v in quote["quotes"]
                    if utc(evaluation["start"])
                    <= utc(v.timestamp)
                    <= utc(evaluation["end"])
                )
                candidates = []
                for spec in specifications():
                    decisions, hashes = decisions_from_candles(
                        spec,
                        costs,
                        dataset.rows["M1"],
                        dataset.rows["M5"],
                        evaluation=evaluation,
                        calendar=dataset.calendar,
                        provenance=dataset.provenance,
                        finality=dataset.finality_attested,
                        feed_id=dataset.metadata["lineage"]["feed_id"],
                    )
                    run = _simulate(
                        spec,
                        costs,
                        quotes,
                        decisions,
                        permissions=permissions,
                        cutoff=evaluation["end"],
                        source_binding=binding,
                    )
                    repeated = _simulate(
                        spec,
                        costs,
                        quotes,
                        decisions,
                        permissions=permissions,
                        cutoff=evaluation["end"],
                        source_binding=binding,
                    )
                    if run != repeated:
                        raise ValueError("REPEATABILITY_FAILED")
                    cutoff = (
                        decisions[len(decisions) // 2].timestamp
                        if decisions
                        else evaluation["start"]
                    )
                    prefix = _simulate(
                        spec,
                        costs,
                        quotes,
                        decisions,
                        permissions=permissions,
                        cutoff=cutoff,
                        source_binding=binding,
                    )
                    overlap = [
                        e for e in run["events"] if utc(e["timestamp"]) <= utc(cutoff)
                    ]
                    if prefix["events"] != overlap:
                        raise ValueError("PREFIX_EQUIVALENCE_FAILED")
                    validation = validation_runs(
                        spec, costs, quotes, decisions, permissions, plan
                    )
                    state, why = qualification_status(
                        q["status"],
                        run,
                        validation=validation,
                        reproduction_review_path=(reproduction_reviews or {}).get(
                            spec.strategy_id
                        ),
                    )
                    candidates.append(
                        dict(
                            strategy_id=spec.strategy_id,
                            specification_sha256=spec.sha256,
                            qualification=state,
                            reason_codes=why,
                            historical_metrics=metrics(run),
                            backtest=run,
                            validation=validation,
                            configuration_hashes=hashes,
                            comparisons=dict(
                                full_full="MATCH", common_cutoff_prefix="MATCH"
                            ),
                            cost_file_sha256=sha256(raw).hexdigest(),
                        )
                    )
                r.update(
                    candidates=candidates,
                    status="WARN",
                    analysis_status="BACKTEST_RESEARCH_COMPLETED_ACCEPTANCE_BLOCKED",
                    comparisons="FULL_FULL_AND_PREFIX_MATCH",
                )
                if any(c["qualification"] == "BACKTEST_QUALIFIED" for c in candidates):
                    r.update(
                        acceptance="STAGE_B_RESEARCH_THRESHOLDS_AND_REPRODUCTION_PASSED",
                        recommendation="PROCEED_TO_STAGE_C_REVIEW_ONLY",
                        status="PASS",
                        analysis_status="STAGE_B_RESEARCH_QUALIFIED_NOT_EXECUTION",
                    )
                    r["later_stages"]["C"][
                        "reason"
                    ] = "ACCOUNT_BOUND_TRANSPORT_STILL_UNVERIFIED"
                else:
                    reasons.append(
                        "INDEPENDENT_BACKTEST_REPRODUCTION_AND_QUALIFICATION_NOT_ESTABLISHED"
                    )
        except Exception as exc:
            code = str(exc)
            allowed = {
                "COST_MODEL_INVALID",
                "DATASET_CHANGED_AFTER_QUALIFICATION",
                "COST_MODEL_REVIEW_BINDING_REQUIRED",
                "VALIDATION_WINDOWS_OUTSIDE_EVALUATION",
                "QUOTE_BAR_ALIGNMENT_UNESTABLISHED",
                "QUOTE_COST_TICK_SIZE_MISMATCH",
                "DATED_SESSION_PERMISSIONS_REQUIRED",
                "REPEATABILITY_FAILED",
                "PREFIX_EQUIVALENCE_FAILED",
                "IS_OOS_LEAKAGE",
                "WALK_FORWARD_LEAKAGE",
                "PREDECLARED_PROTOCOL_MISMATCH",
            }
            reasons.append(
                code
                if code in allowed
                else "EXECUTABLE_STUDY_INPUT_OR_EVIDENCE_UNAVAILABLE"
            )
    r["reason_codes"] = sorted(set(reasons))
    if r["status"] == "BLOCKED":
        for c in r["candidates"]:
            c["reason_codes"] = r["reason_codes"]
    r["sha256"] = digest(r)
    return r


def validate_study(r):
    need = lambda ok: (
        None if ok else (_ for _ in ()).throw(ValueError("Invalid Stage-B study"))
    )
    need(
        type(r) is dict
        and set(r) == set(empty_study()) | {"sha256"}
        and r["status"] in ("PASS", "WARN", "FAIL", "BLOCKED")
        and r["study_version"] == 1
        and type(r["study_version"]) is int
        and r["stage"] == "B"
    )
    need(r["sha256"] == digest({k: v for k, v in r.items() if k != "sha256"}))
    need(
        r["safety"] == safety()
        and r["exness"] == "BLOCKED"
        and r["historical_validation"] == "PENDING"
        and r["historical_comparisons"] == "NOT_RUN"
    )
    need(
        r["protocol"] == PROTOCOL
        and r["protocol_sha256"] == PROTOCOL_SHA256
        and r["specifications"] == [s.description() for s in specifications()]
    )
    need(
        len(r["candidates"]) == 2
        and [c["strategy_id"] for c in r["candidates"]]
        == [s.strategy_id for s in specifications()]
    )
    for spec, c in zip(specifications(), r["candidates"]):
        need(
            c["specification_sha256"] == spec.sha256
            and c["qualification"] in QUALIFICATION_STATES
        )
        if c["backtest"] is None:
            need(
                c["historical_metrics"] is None
                and c["validation"] is None
                and c["qualification"] in ("DATA_NOT_QUALIFIED", "EXPERIMENTAL")
            )
        else:
            run = c["backtest"]
            need(
                run["sha256"] == digest({k: v for k, v in run.items() if k != "sha256"})
                and run["events_sha256"] == digest(run["events"])
            )
            need(
                c["historical_metrics"] == metrics(run)
                and r["source_qualification"]["status"]
                == "HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED"
                and r["quote_qualification"]["status"] == "QUOTE_PRECHECKS_PASSED"
            )
    if not any(c["backtest"] is not None for c in r["candidates"]):
        need(
            r["status"] in ("FAIL", "BLOCKED")
            and r["analysis_status"] == "NOT_RUN"
            and r["comparisons"] == "NOT_RUN"
            and r["acceptance"] == "NOT_ESTABLISHED"
        )
    if any(c["backtest"] is not None for c in r["candidates"]):
        paths = r["inputs"]
        need(isinstance(paths, dict))
        expected = run_study(
            paths["manifest"],
            paths["review"],
            paths["quotes"],
            paths["costs"],
            paths["plan"],
            paths["reproductions"],
        )
        need(
            expected == r
        )  # Re-read sources/reviews and recompute, never trust edited metrics/statuses.
    qualified = any(c["qualification"] == "BACKTEST_QUALIFIED" for c in r["candidates"])
    need((r["recommendation"] == "PROCEED_TO_STAGE_C_REVIEW_ONLY") == qualified)
    if qualified:
        need(
            r["status"] == "PASS"
            and r["analysis_status"] == "STAGE_B_RESEARCH_QUALIFIED_NOT_EXECUTION"
        )
    else:
        need(r["recommendation"] == "BLOCKED")
    need(
        all(r["later_stages"][s]["status"] == "BLOCKED_NOT_STARTED" for s in ("C", "D"))
    )
    return True
