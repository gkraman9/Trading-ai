"""E1: bounded, source-bound SR research projection. No acquisition or execution."""

from copy import deepcopy
from datetime import datetime
import re

from iat.paper_source_scope import current_source, context_allowed
from iat.replay_dataset import utc
from iat.intelligence.context_models import ContextReport
from iat.intelligence.market_view import SAFETY, plain, validate_market_view_v3
from iat.intelligence.sr_rejection import (
    SRRejectionLedger,
    validate_sr_result,
    STRATEGY,
    RULE,
    POLICY as SR_POLICY,
)
from iat.intelligence.strategy_replay import digest

MODEL = "IAT_ENTRY_INTELLIGENCE_V1"
STATES = (
    "NO_SETUP",
    "WATCHING",
    "AWAITING_CONFIRMATION",
    "RESEARCH_QUALIFIED",
    "ABSTAINED",
    "INVALIDATED",
    "EXPIRED",
    "BLOCKED",
)
STATE_MAP = dict(
    CANDIDATE="AWAITING_CONFIRMATION",
    QUALIFIED="RESEARCH_QUALIFIED",
    ABSTAINED="ABSTAINED",
    INVALIDATED="INVALIDATED",
    EXPIRED="EXPIRED",
)
POLICY = dict(
    version=1,
    strategy="UNCHANGED_SR_REJECTION_V1",
    provenance="SYNTHETIC_ONLY_NO_HISTORICAL_LABEL_OVERRIDE",
    fill="NOT_MODELLED_NEXT_VALIDATED_SIDE_SPECIFIC_OBSERVATION_REQUIRED",
    cutoff="EXACT_SOURCE_M1_CLOSE",
    max_snapshots=256,
    max_sources=10000,
    max_setups=2048,
    watching="RESERVED_NOT_EMITTED_WITHOUT_UPSTREAM_PREDICATE",
)
LIMITATIONS = [
    "SYNTHETIC_ONLY_NOT_MARKET_VALIDATION",
    "RESEARCH_QUALIFIED_IS_NOT_A_SIGNAL",
    "ZONE_REFERENCE_IS_NOT_AN_EXECUTABLE_ENTRY_PRICE",
    "NO_FILL_OR_TRANSACTION_COST_MODEL",
    "M1_M5_DISAGREEMENT_DOES_NOT_ESTABLISH_REVERSAL_OR_PULLBACK",
    "UPSTREAM_SR_CONTRACT_DOES_NOT_DECLARE_BID_ASK_BASIS_OR_SPREAD",
    "NO_CONFIDENCE_PROBABILITY_OR_PERFORMANCE_CLAIM",
]


class EntryInputError(ValueError):
    pass


def need(value, code):
    if not value:
        raise EntryInputError(code)


def seal(value):
    value = plain(value)
    return dict(value, sha256=digest(value))


def blocked_entry(code="ENTRY_INPUT_UNAVAILABLE"):
    """Canonical empty availability report; never contains a cached plan."""
    need(
        isinstance(code, str) and re.fullmatch("[A-Z0-9_]+", code),
        "ENTRY_REASON_INVALID",
    )
    return seal(
        dict(
            report_version=1,
            model_version=MODEL,
            status="BLOCKED",
            validation_status="SYNTHETIC_ONLY",
            symbol=None,
            evaluation_at_utc=None,
            provenance=None,
            strategy=dict(strategy_id=STRATEGY, rule_version=RULE),
            bindings=dict(
                view=None,
                context=None,
                sr_result=None,
                sr_log=None,
                configuration_hashes={},
                sr_policy=digest(SR_POLICY),
                entry_policy=digest(POLICY),
            ),
            market_suitability=None,
            research_states=["BLOCKED"],
            plans=[],
            evidence={},
            price_observation=dict(
                status="UNAVAILABLE",
                bid=None,
                ask=None,
                spread=None,
                price_basis=None,
                reason_codes=["UPSTREAM_SR_PRICE_BASIS_NOT_DECLARED"],
            ),
            exit_research=dict(status="NOT_IMPLEMENTED", version=None),
            risk_research=dict(status="NOT_IMPLEMENTED", version=None),
            paper_research=dict(
                status="NOT_IMPLEMENTED", fill=None, performance_metrics=None
            ),
            reason_codes=[code],
            limitations=LIMITATIONS,
            **SAFETY
        )
    )


def _project(ledger, view, context):
    log = ledger.to_dict()
    result = log["entries"][-1]["result"]
    if result["status"] == "BLOCKED":
        out = blocked_entry("UPSTREAM_SR_BLOCKED")
        out["reason_codes"] = sorted(
            set(result["reason_codes"] + ["UPSTREAM_SR_BLOCKED"])
        )
        # Bind the blocked diagnostic, but never surface frozen qualified plans.
        out["bindings"].update(
            view=view["sha256"],
            context=view["bindings"]["context"],
            sr_result=result["sha256"],
            sr_log=log["sha256"],
        )
        return seal({k: v for k, v in out.items() if k != "sha256"})
    at = utc(result["evaluation_at_utc"])
    plans = []
    catalog = {}
    for entry in log["entries"]:
        for key, value in entry["result"]["evidence"].items():
            need(key not in catalog or catalog[key] == value, "ENTRY_EVIDENCE_REVISED")
            catalog[key] = value
    need(len(catalog) <= POLICY["max_sources"], "ENTRY_RESOURCE_LIMIT")
    used = set()
    for s in log["setups"]:
        refs = sorted(
            set(
                s["supporting_evidence"]
                + s["contradictory_evidence"]
                + result["current_opposition"][s["direction"]]
            )
        )
        used.update(refs)
        c = s["candles"]["C"]
        confirmation = catalog[c] if c else None
        qualified = s["qualified_at_utc"]
        transitions = [
            deepcopy(t)
            for e in log["entries"]
            for t in e["transitions"]
            if t["setup_id"] == s["setup_id"]
        ]
        missing = (
            ["IMMEDIATELY_FOLLOWING_CLOSED_M1_CONFIRMATION_REQUIRED"]
            if c is None
            else []
        )
        reasons = transitions[-1]["reason_codes"] if transitions else s["reason_codes"]
        plans.append(
            dict(
                setup_id=s["setup_id"],
                strategy_id=STRATEGY,
                rule_version=RULE,
                research_direction=s["direction"],
                research_state=STATE_MAP[s["state"]],
                entry_location=dict(
                    reference_type="FROZEN_UPSTREAM_ZONE_REFERENCE",
                    **deepcopy(s["zone"])
                ),
                confirmation=dict(
                    candle_ids=deepcopy(s["candles"]),
                    predicate_scope="UPSTREAM_ANCHORED_SNAPSHOT_NOT_NEW_ENTRY_AUTHORIZATION",
                    predicates=deepcopy(s["conditions"]),
                    event_opened_at_utc=(
                        confirmation["observed_at"] if confirmation else None
                    ),
                    event_available_at_utc=(
                        confirmation["available_at"] if confirmation else None
                    ),
                    earliest_research_qualification_at_utc=qualified,
                    missing_evidence=missing,
                ),
                supporting_evidence=deepcopy(s["supporting_evidence"]),
                contradictory_evidence=sorted(
                    set(
                        s["contradictory_evidence"]
                        + result["current_opposition"][s["direction"]]
                    )
                ),
                structural_invalidation=dict(
                    zone_id=s["zone"]["id"],
                    lower=s["zone"]["lower"],
                    upper=s["zone"]["upper"],
                    break_tolerance=result["bindings"]["configuration_hashes"][
                        "break_tolerance"
                    ],
                    conditions=deepcopy(s["invalidation_conditions"]),
                ),
                relevant_level_references=[s["zone"]["id"]],
                setup_age=dict(
                    first_seen_at_utc=s["first_seen_at_utc"],
                    elapsed_seconds=(at - utc(s["first_seen_at_utc"])).total_seconds(),
                    eligible_closes_after_confirmation=s["eligible_closes_after_C"],
                ),
                evaluation_at_utc=result["evaluation_at_utc"],
                lifecycle_events=transitions,
                timing_research=dict(
                    earliest_confirmation_at_utc=qualified,
                    fill=None,
                    fill_status="NOT_MODELLED",
                    future_observation_required="VALIDATED_BID_ASK_TICK_STRICTLY_AFTER_CONFIRMATION_AND_FILL_COST_MODEL",
                ),
                reason_codes=deepcopy(reasons),
                explanation=[
                    "Location and predicates are unchanged upstream SR research observations.",
                    "A zone interval is a hypothesis reference, not a hypothetical fill.",
                    "No directional authorization follows from research qualification.",
                    "RESEARCH_QUALIFIED describes the original SR lifecycle, not a new entry at this cutoff.",
                ],
            )
        )
    need(used <= set(catalog), "ENTRY_EVIDENCE_UNRESOLVED")
    out = blocked_entry()
    out.pop("sha256")
    out.update(
        status="EVALUATED",
        symbol=result["symbol"],
        evaluation_at_utc=result["evaluation_at_utc"],
        provenance=result["provenance"],
        market_suitability=dict(
            observed_market_state=deepcopy(view["market_state"]),
            m1_m5_context=deepcopy(context.context),
            liquidity=deepcopy(view["liquidity"]),
            restrictions=deepcopy(view["restrictions"]),
            interpretation="UPSTREAM_FACTS_NOT_NEW_STRATEGY_PREDICATES",
        ),
        plans=plans,
        research_states=sorted({p["research_state"] for p in plans}) or ["NO_SETUP"],
        evidence={k: catalog[k] for k in sorted(used)},
        reason_codes=["RESEARCH_ONLY_CONTINUE_WAITING"],
    )
    out["bindings"].update(
        view=view["sha256"],
        context=view["bindings"]["context"],
        sr_result=result["sha256"],
        sr_log=log["sha256"],
        configuration_hashes=deepcopy(result["bindings"]["configuration_hashes"]),
    )
    return seal(out)


class EntryResearchSession:
    """Single-threaded bounded research session; no deserialized log grants eligibility.

    Only typed synthetic context and the source-bound V3 view enter the SR public
    interface. Historical integration requires a future manifest-gated bridge;
    a provenance string or arbitrary serialized SR result is never accepted here.
    Returned reports/logs are deep copies; failed input never advances lifecycle.
    """

    def __init__(self):
        self._historical_source = current_source()
        self._ledger = SRRejectionLedger()
        self._last = blocked_entry()
        self._produced = set()  # At most one hash per accepted, bounded SR snapshot.

    def record(self, view, context, *, view_inputs=None, as_of=None):
        try:
            need(isinstance(context, ContextReport), "ENTRY_TYPED_CONTEXT_REQUIRED")
            need(
                context_allowed(context, self._historical_source),
                "ENTRY_SYNTHETIC_ONLY",
            )
            at = utc(context.analysis_at)
            cutoff = (
                at
                if as_of is None
                else utc(as_of.isoformat() if isinstance(as_of, datetime) else as_of)
            )
            need(at <= cutoff, "ENTRY_FUTURE_SOURCE")
            need(at == cutoff, "ENTRY_SOURCE_NOT_CURRENT")
            need(
                len(context.interpretations.get("source_registry", {}))
                <= POLICY["max_sources"],
                "ENTRY_RESOURCE_LIMIT",
            )
            if self._ledger.last is not None:
                same = context.analysis_at == self._ledger.last["evaluation_at_utc"]
                need(
                    same or len(self._ledger.entries) < POLICY["max_snapshots"],
                    "ENTRY_RESOURCE_LIMIT",
                )
            validate_market_view_v3(view, context_report=context, **(view_inputs or {}))
            candidate = deepcopy(self._ledger)
            if self._historical_source is None:
                entry = candidate.record(view, context, view_inputs=view_inputs)
            else:
                from iat.intelligence.sr_rejection import _evaluate

                entry = candidate._record(
                    _evaluate(
                        view,
                        context,
                        view_inputs=view_inputs,
                        dataset=self._historical_source.dataset_id,
                    )
                )
            validate_sr_result(
                entry["result"],
                **(
                    dict(view=view, context=context, view_inputs=view_inputs)
                    if self._historical_source is None
                    else {}
                )
            )
            need(len(candidate.setups) <= POLICY["max_setups"], "ENTRY_RESOURCE_LIMIT")
            report = _project(candidate, view, context)
            if self._historical_source is not None and report["status"] == "EVALUATED":
                report.pop("sha256")
                report["validation_status"] = (
                    "FILE_BOUND_RESEARCH_NOT_STRATEGY_VALIDATED"
                )
                report["price_observation"].update(
                    status="QUALIFIED_CANDLE_BASIS_ONLY",
                    price_basis=self._historical_source.price_basis,
                    reason_codes=["NO_EXECUTABLE_QUOTE_IN_ENTRY_REPORT"],
                )
                report["limitations"] = [
                    x
                    for x in report["limitations"]
                    if x != "SYNTHETIC_ONLY_NOT_MARKET_VALIDATION"
                ]
                report["limitations"].append(
                    "QUALIFIED_INPUTS_DO_NOT_ESTABLISH_STRATEGY_PERFORMANCE"
                )
                report = seal(report)
            self._ledger = candidate
            self._last = report
            self._produced.add(report["sha256"])
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
            OverflowError,
            RecursionError,
        ) as exc:
            code = (
                str(exc)
                if isinstance(exc, EntryInputError)
                else "ENTRY_SOURCE_OR_LIFECYCLE_INVALID"
            )
            self._last = blocked_entry(code)
        return deepcopy(self._last)

    def fork_at(self, report):
        """Isolate an authenticated produced report's exact prefix, excluding future state.

        This is not an arbitrary log importer or qualification/approval interface.
        """
        validate_entry_report(report, source=self)
        need(report["status"] == "EVALUATED", "ENTRY_EVALUATED_FORK_REQUIRED")
        prefix = SRRejectionLedger()
        found = False
        for entry in self._ledger.entries:
            prefix._record(deepcopy(entry["result"]))
            if entry["result"]["sha256"] == report["bindings"]["sr_result"]:
                found = True
                break
        need(
            found and prefix.to_dict()["sha256"] == report["bindings"]["sr_log"],
            "ENTRY_FORK_PREFIX_BINDING_INVALID",
        )
        child = EntryResearchSession()
        child._ledger = prefix
        child._last = deepcopy(report)
        child._produced = {report["sha256"]}
        return child

    def report(self):
        return deepcopy(self._last)

    def sr_log(self):
        return deepcopy(self._ledger.to_dict())


def assess_entry(view, context, **options):
    """One snapshot only. Retain EntryResearchSession for lifecycle/expiry research."""
    return EntryResearchSession().record(view, context, **options)


def validate_entry_report(report, *, source=None):
    """Verify serialized output against its producing session, not a caller label.

    BLOCKED empty reports can be checked standalone. EVALUATED reports require
    the original in-process research session. Offline audit-log import/approval
    is not implemented by E1; checksum-only authenticity is never claimed.
    """
    try:
        need(
            type(report) is dict and set(report) == set(blocked_entry()),
            "ENTRY_REPORT_SCHEMA_INVALID",
        )
        need(
            type(report["report_version"]) is int
            and report["report_version"] == 1
            and report["model_version"] == MODEL,
            "ENTRY_REPORT_VERSION_INVALID",
        )
        need(
            report["sha256"]
            == digest({k: v for k, v in report.items() if k != "sha256"}),
            "ENTRY_REPORT_CHECKSUM_INVALID",
        )
        for k, v in SAFETY.items():
            need(
                type(report[k]) is type(v) and report[k] == v,
                "ENTRY_REPORT_SAFETY_INVALID",
            )
        if report["status"] == "EVALUATED":
            need(
                type(source) is EntryResearchSession, "ENTRY_PRODUCING_SESSION_REQUIRED"
            )
            need(
                report["sha256"] in source._produced,
                "ENTRY_REPORT_SOURCE_BINDING_INVALID",
            )
        else:
            need(
                report["status"] == "BLOCKED"
                and not report["plans"]
                and not report["evidence"]
                and report["research_states"] == ["BLOCKED"],
                "ENTRY_BLOCKED_HAS_PLAN",
            )
            canonical = blocked_entry()
            for k in set(canonical) - {"sha256", "reason_codes", "bindings"}:
                need(report[k] == canonical[k], "ENTRY_BLOCKED_SCHEMA_INVALID")
            need(
                type(report["reason_codes"]) is list
                and report["reason_codes"]
                and all(
                    isinstance(c, str) and re.fullmatch("[A-Z0-9_]+", c)
                    for c in report["reason_codes"]
                ),
                "ENTRY_REASON_INVALID",
            )
            need(
                type(report["bindings"]) is dict
                and set(report["bindings"]) == set(canonical["bindings"]),
                "ENTRY_BINDINGS_INVALID",
            )
            for k in ("entry_policy", "sr_policy", "configuration_hashes"):
                need(
                    report["bindings"][k] == canonical["bindings"][k],
                    "ENTRY_BINDINGS_INVALID",
                )
            for k in ("view", "context", "sr_result", "sr_log"):
                value = report["bindings"][k]
                need(
                    value is None
                    or isinstance(value, str)
                    and re.fullmatch("[a-f0-9]{64}", value),
                    "ENTRY_BINDINGS_INVALID",
                )
    except (
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OverflowError,
        RecursionError,
    ):
        raise ValueError("ENTRY_REPORT_SCHEMA_INVALID") from None
    return True
