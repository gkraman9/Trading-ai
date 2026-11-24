"""Manifest-gated research extension replay; no qualification promotion or execution."""

from copy import deepcopy
from datetime import timedelta
from iat.replay_dataset import load_dataset, DatasetError, utc
from iat.historical_replay import dataset_preflight
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.market_view import build_market_view_v3, SAFETY
from iat.intelligence.sr_rejection import (
    SRRejectionLedger,
    _evaluate,
    validate_sr_log,
    seal,
    need,
)
from iat.intelligence.strategy_replay import digest


def _replay(
    symbol,
    one,
    five,
    *,
    config,
    intelligence_config,
    calendar=None,
    observed_finality=None,
    provenance="SYNTHETIC_RESEARCH",
    as_of=None,
    dataset=None
):
    need(
        isinstance(config, ContextConfig)
        and isinstance(intelligence_config, IntelligenceConfig),
        "SR_TYPED_CONFIGURATIONS_REQUIRED",
    )
    ledger = SRRejectionLedger()
    previous = None
    for index, row in enumerate(one):
        at = utc(row["timestamp"]) + timedelta(minutes=1)
        if as_of is not None and at > utc(
            as_of.isoformat() if hasattr(as_of, "isoformat") else as_of
        ):
            break
        need(
            index < 5000 and (previous is None or at > previous),
            "SR_REPLAY_CHRONOLOGY_OR_LIMIT",
        )
        context = context_at(
            symbol,
            one,
            five,
            at,
            config=config,
            intelligence_config=intelligence_config,
            calendar=calendar,
            observed_finality=observed_finality,
            provenance=provenance,
        )
        inputs = (
            dict(session_snapshot=calendar.public_state(at))
            if getattr(calendar, "version", 1) == 2
            else {}
        )
        view = build_market_view_v3(context, **inputs)
        ledger._record(_evaluate(view, context, view_inputs=inputs, dataset=dataset))
        previous = at
    log = ledger.to_dict()
    validate_sr_log(log)
    return log


def replay_sr_rejection(
    symbol,
    one,
    five,
    *,
    config=None,
    intelligence_config=None,
    as_of=None,
    calendar=None,
    observed_finality=None
):
    """Labeled synthetic software replay; no caller historical-provenance override."""
    return _replay(
        symbol,
        one,
        five,
        config=ContextConfig() if config is None else config,
        intelligence_config=(
            IntelligenceConfig() if intelligence_config is None else intelligence_config
        ),
        as_of=as_of,
        calendar=calendar,
        observed_finality=observed_finality,
    )


def run_sr_manifest(path=None, *, config=None, intelligence_config=None, as_of=None):
    """Only this loader/preflight path can produce historical-labeled observations.

    Even eligible inputs do not establish historical validation of the new rule.
    """
    result = dict(
        dataset_result_version=1,
        kind="SR_REJECTION_DATASET_RESEARCH",
        status="BLOCKED",
        reason_codes=["DATASET_UNAVAILABLE"],
        dataset=None,
        preflight=None,
        replay=None,
        evaluation_start_utc=None,
        evaluation_end_utc=None,
        window_accounting=None,
        historical_metrics=None,
        **SAFETY
    )
    if path is None:
        return seal(result)
    config = ContextConfig() if config is None else config
    intelligence_config = (
        IntelligenceConfig() if intelligence_config is None else intelligence_config
    )
    try:
        dataset = load_dataset(path)
        result["dataset"] = deepcopy(dataset.metadata)
        checked = dataset_preflight(dataset, intelligence_config=intelligence_config)
        result["preflight"] = checked["preflight"]
        if checked["status"] != "READY":
            result["reason_codes"] = checked["reason_codes"]
            return seal(result)
        historical = dataset.metadata["dataset_kind"] == "INDEPENDENT_HISTORICAL"
        if historical:
            need(
                dataset.metadata["manifest_version"] == 2
                and dataset.metadata["lineage"]["m5_origin"] == "NATIVE_SAME_FEED"
                and checked["preflight"]["alignment"]["evaluation"][
                    "coverage_sufficient"
                ]
                and checked["preflight"]["alignment"]["evaluation"]["cross_frame_claim"]
                == "SCOPED_SAME_FEED_CONSISTENCY",
                "SR_NATIVE_EVALUATION_EVIDENCE_REQUIRED",
            )
        log = _replay(
            "XAUUSD",
            dataset.rows["M1"],
            dataset.rows["M5"],
            config=config,
            intelligence_config=intelligence_config,
            calendar=dataset.calendar,
            observed_finality=dataset.finality_attested,
            provenance=dataset.provenance,
            as_of=as_of,
            dataset=digest(dataset.metadata),
        )
        evaluation = dataset.metadata.get("evaluation", dataset.metadata["utc_range"])
        boundary = utc(evaluation["start"])
        warm = [
            e
            for e in log["entries"]
            if utc(e["result"]["evaluation_at_utc"]) <= boundary
        ]
        selected = [
            e
            for e in log["entries"]
            if boundary
            < utc(e["result"]["evaluation_at_utc"])
            <= utc(evaluation["end"])
        ]
        active = set()
        for e in warm:
            for t in e["transitions"]:
                if t["to_state"] == "QUALIFIED":
                    active.add(t["setup_id"])
                elif t["to_state"] in ("INVALIDATED", "EXPIRED", "ABSTAINED"):
                    active.discard(t["setup_id"])
        result.update(
            status="WARN",
            reason_codes=["SYNTHETIC_ONLY_RULE_HISTORICAL_VALIDATION_PENDING"],
            replay=log,
            evaluation_start_utc=evaluation["start"],
            evaluation_end_utc=evaluation["end"],
            window_accounting=dict(
                warmup_snapshots=len(warm),
                evaluation_snapshots=len(selected),
                evaluation_blocked=sum(
                    e["result"]["status"] == "BLOCKED" for e in selected
                ),
                carried_in_qualified_setup_ids=sorted(active),
                evaluation_first_qualifications=sorted(
                    {
                        t["setup_id"]
                        for e in selected
                        for t in e["transitions"]
                        if t["to_state"] == "QUALIFIED"
                    }
                ),
            ),
        )
    except DatasetError as exc:
        result["reason_codes"] = [exc.code]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        result["reason_codes"] = ["SR_DATASET_RESEARCH_BLOCKED"]
    return seal(result)
