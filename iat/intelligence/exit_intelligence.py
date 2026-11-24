"""E2 source-bound synthetic observations; no positions, fills or execution."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import re
from iat.replay_dataset import utc
from iat.intelligence.context_models import ContextReport
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    validate_entry_report,
)
from iat.intelligence.market_view import SAFETY, plain
from iat.intelligence.strategy_replay import digest

MODEL = "IAT_EXIT_INTELLIGENCE_V1"
LIMITS = dict(max_reports=256, max_events=256)


class ExitInputError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ExitInputError(code)


def seal(value):
    value = plain(value)
    return dict(value, sha256=digest(value))


@dataclass(frozen=True)
class ExitPolicy:
    version: int = 1
    target_observation: str = "WICK_CONTACT"

    def __post_init__(self):
        need(
            type(self.version) is int and self.version == 1, "E2_POLICY_VERSION_INVALID"
        )
        need(
            self.target_observation in ("WICK_CONTACT", "CLOSE_BEYOND_REFERENCE"),
            "E2_TARGET_POLICY_INVALID",
        )


def blocked_exit(code="E2_ORIGINAL_SOURCE_UNAVAILABLE"):
    need(
        isinstance(code, str) and re.fullmatch("[A-Z0-9_]+", code), "E2_REASON_INVALID"
    )
    return seal(
        dict(
            report_version=1,
            model_version=MODEL,
            exit_policy_version=1,
            exit_policy=None,
            source_eligibility="BLOCKED",
            validation_status="SYNTHETIC_ONLY",
            original=None,
            current_observation_cutoff_utc=None,
            original_hypothesis_lifecycle=None,
            frozen_invalidation=None,
            frozen_target=None,
            target_candidates=[],
            target_status="TARGET_UNAVAILABLE",
            observations=[],
            supporting_evidence=[],
            contradictory_evidence=[],
            missing_evidence=[code],
            analytical_states=["BLOCKED"],
            hypothesis_assessment="UNAVAILABLE",
            ambiguity=dict(status="NOT_ASSESSED", groups=[]),
            source_restrictions=None,
            bindings=dict(
                original_e1=None,
                current_e1=None,
                view=None,
                context=None,
                sr_log=None,
                configurations={},
                exit_policy=None,
            ),
            explanation=[
                "Analytical observations do not establish an open position or an exit."
            ],
            entry_fill=None,
            exit_fill=None,
            realized_pnl=None,
            hypothetical_pnl=None,
            holding_duration=None,
            performance_metrics=None,
            timer_exit="NOT_IMPLEMENTED",
            reason_codes=[code],
            **SAFETY
        )
    )


def _targets(row, close, at):
    direction = row["direction"]
    kind = "RESISTANCE" if direction == "BULLISH" else "SUPPORT"
    candidates = deepcopy(row["exit_hypothesis"]["opposing_zones"])
    ids = []
    for z in candidates:
        need(
            z["kind"] == kind
            and z["status"] in ("FRESH", "TESTED")
            and utc(z["confirmed_at"]) <= at,
            "E2_ORIGINAL_TARGET_INELIGIBLE",
        )
        need(
            z["lower"] > close if direction == "BULLISH" else z["upper"] < close,
            "E2_TARGET_NOT_OPPOSING",
        )
        ids.append(z["id"])
    need(len(ids) == len(set(ids)), "E2_DUPLICATE_TARGET_REFERENCE")
    # Distances rank existing references; they never mint an executable price.
    candidates.sort(
        key=lambda z: (
            (z["lower"] - close if direction == "BULLISH" else close - z["upper"]),
            z["id"],
        )
    )
    return candidates


class ExitResearchSession:
    """Single-threaded, one original setup; source failures never reset lifecycle.

    E1 authenticates the original and forks only its original trusted prefix.
    Later E1 records are performed on transactionally staged independent state.
    """

    def __init__(self, original=None, setup_id=None, *, entry_source=None, policy=None):
        self._ready = False
        self._last = blocked_exit()
        self._produced = set()
        self._events = {}
        self._gap = False
        try:
            need(
                type(entry_source) is EntryResearchSession,
                "E2_ORIGINAL_PRODUCER_REQUIRED",
            )
            validate_entry_report(original, source=entry_source)
            need(
                original["status"] == "EVALUATED"
                and original["provenance"] == "SYNTHETIC_RESEARCH",
                "E2_SYNTHETIC_ORIGINAL_REQUIRED",
            )
            plans = [p for p in original["plans"] if p["setup_id"] == setup_id]
            need(
                len(plans) == 1 and plans[0]["research_state"] == "RESEARCH_QUALIFIED",
                "E2_QUALIFIED_ORIGINAL_REQUIRED",
            )
            plan = deepcopy(plans[0])
            qualified = utc(
                plan["confirmation"]["earliest_research_qualification_at_utc"]
            )
            need(
                qualified == utc(original["evaluation_at_utc"]),
                "E2_ORIGINAL_QUALIFICATION_CUTOFF_REQUIRED",
            )
            chosen = ExitPolicy() if policy is None else policy
            need(type(chosen) is ExitPolicy, "E2_TYPED_POLICY_REQUIRED")
            entry = entry_source.fork_at(original)
            result = entry.sr_log()["entries"][-1]["result"]
            rows = [
                r
                for r in result["evaluations"]
                if r["setup_id"] == setup_id and r["state"] == "QUALIFIED"
            ]
            need(len(rows) == 1, "E2_ORIGINAL_SR_ANCHOR_REQUIRED")
            self._policy = chosen
            self._entry = entry
            self._plan = plan
            self._original = deepcopy(original)
            self._qualified = qualified
            self._targets = _targets(rows[0], result["current_bar"]["close"], qualified)
            self._last_at = qualified
            self._lifecycle = "RESEARCH_QUALIFIED"
            self._last = self._report(original, [], False)
            self._produced.add(self._last["sha256"])
            self._ready = True
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
            OverflowError,
            RecursionError,
        ) as exc:
            self._last = blocked_exit(
                str(exc)
                if isinstance(exc, ExitInputError)
                else "E2_ORIGINAL_BINDING_INVALID"
            )

    def _report(self, current, events, gap):
        plan = next(
            p for p in current["plans"] if p["setup_id"] == self._plan["setup_id"]
        )
        groups = []
        by_bar = {}
        for e in events:
            by_bar.setdefault(e["available_at_utc"], []).append(e)
        for at, es in sorted(by_bar.items()):
            kinds = {e["kind"] for e in es}
            if "STRUCTURAL_TARGET_OBSERVED" in kinds and kinds & {
                "STRUCTURAL_INVALIDATION_OBSERVED",
                "OPPOSING_STRUCTURE_OBSERVED",
                "HYPOTHESIS_EXPIRED",
            }:
                groups.append(
                    dict(
                        available_at_utc=at,
                        event_ids=sorted(e["id"] for e in es),
                        status="UNRESOLVED_EVENT_ORDER",
                        timing_basis=(
                            "UNKNOWN_INTRABAR_ORDER"
                            if any(e["occurred_at_utc"] is None for e in es)
                            else "SIMULTANEOUS_CLOSE_AVAILABILITY"
                        ),
                    )
                )
        states = {e["kind"] for e in events}
        if plan["research_state"] == "RESEARCH_QUALIFIED":
            states.add("MONITORING_HYPOTHESIS")
        if not self._targets:
            states.add("NO_EXIT_REFERENCE")
        if groups:
            states.add("UNRESOLVED_EVENT_ORDER")
        if gap:
            states.add("ABSTAINED")
        if not states:
            states.add("NOT_APPLICABLE")
        result = blocked_exit()
        result.pop("sha256")
        result.update(
            source_eligibility="VALID",
            exit_policy=asdict(self._policy),
            original=dict(
                setup_id=self._plan["setup_id"],
                entry_report_sha256=self._original["sha256"],
                research_direction=self._plan["research_direction"],
                qualification_at_utc=self._qualified.isoformat(),
            ),
            current_observation_cutoff_utc=current["evaluation_at_utc"],
            original_hypothesis_lifecycle=dict(
                state=plan["research_state"],
                eligible_closes_after_confirmation=plan["setup_age"][
                    "eligible_closes_after_confirmation"
                ],
                scope="RESEARCH_SETUP_NOT_POSITION",
            ),
            frozen_invalidation=deepcopy(self._plan["structural_invalidation"]),
            frozen_target=deepcopy(self._targets[0]) if self._targets else None,
            target_candidates=deepcopy(self._targets),
            target_status=(
                "FROZEN_AT_QUALIFICATION" if self._targets else "TARGET_UNAVAILABLE"
            ),
            observations=deepcopy(events),
            supporting_evidence=sorted(
                set(
                    self._plan["supporting_evidence"]
                    + [r for e in events for r in e["source_references"]]
                )
            ),
            contradictory_evidence=sorted(
                {
                    r
                    for e in events
                    if e["kind"]
                    in (
                        "STRUCTURAL_INVALIDATION_OBSERVED",
                        "OPPOSING_STRUCTURE_OBSERVED",
                    )
                    for r in e["source_references"]
                }
            ),
            missing_evidence=(
                ["INTERVENING_EXIT_OBSERVATIONS_NOT_EVALUATED"] if gap else []
            ),
            analytical_states=sorted(states),
            hypothesis_assessment=(
                "UNKNOWN_DURING_UNOBSERVED_INTERVALS" if gap else plan["research_state"]
            ),
            ambiguity=dict(
                status=(
                    "UNRESOLVED_EVENT_ORDER"
                    if groups
                    else "NO_COAVAILABLE_CONFLICT_OBSERVED"
                ),
                groups=groups,
            ),
            source_restrictions=deepcopy(current["market_suitability"]["restrictions"]),
            bindings=dict(
                original_e1=self._original["sha256"],
                current_e1=current["sha256"],
                view=current["bindings"]["view"],
                context=current["bindings"]["context"],
                sr_log=current["bindings"]["sr_log"],
                configurations=deepcopy(current["bindings"]["configuration_hashes"]),
                exit_policy=digest(asdict(self._policy)),
            ),
            reason_codes=["ANALYTICAL_ONLY_NO_POSITION_OR_FILL"]
            + (["TARGET_UNAVAILABLE"] if not self._targets else []),
        )
        return seal(result)

    def record(self, view, context, *, view_inputs=None, as_of=None):
        if not self._ready:
            return deepcopy(self._last)
        try:
            need(
                isinstance(context, ContextReport)
                and context.provenance == "SYNTHETIC_RESEARCH",
                "E2_SYNTHETIC_CURRENT_REQUIRED",
            )
            at = utc(context.analysis_at)
            cutoff = (
                at
                if as_of is None
                else utc(as_of.isoformat() if isinstance(as_of, datetime) else as_of)
            )
            need(at == cutoff and at >= self._last_at, "E2_CURRENT_CUTOFF_INVALID")
            candidate = deepcopy(self._entry)
            current = candidate.record(
                view, context, view_inputs=view_inputs, as_of=cutoff
            )
            if current["status"] == "BLOCKED":
                # Accept only genuine source-bound blocked SR observations into the source clock.
                if "UPSTREAM_SR_BLOCKED" in current["reason_codes"]:
                    self._entry = candidate
                    self._gap = True
                self._last = blocked_exit("E2_CURRENT_SOURCE_BLOCKED")
                return deepcopy(self._last)
            validate_entry_report(current, source=candidate)
            events = deepcopy(self._events)
            gap = self._gap or at - self._last_at > timedelta(minutes=1)
            # Repeated snapshots do not imply missed observations.
            if at == self._last_at:
                gap = self._gap
            result = candidate.sr_log()["entries"][-1]["result"]
            bar = result["current_bar"]
            sources = context.interpretations["source_registry"]

            def add(
                kind, refs, *, event_id=None, occurred=None, interval=None, details=None
            ):
                key = "E2EVENT:" + digest(
                    [self._plan["setup_id"], kind, event_id or bar["id"]]
                )
                events.setdefault(
                    key,
                    dict(
                        id=key,
                        kind=kind,
                        canonical_event_id=event_id,
                        source_references=sorted(set(refs)),
                        occurred_at_utc=occurred,
                        occurred_interval_utc=interval,
                        available_at_utc=bar["closed_at"],
                        first_observed_at_utc=at.isoformat(),
                        details=details or {},
                    ),
                )

            prior = (
                self._lifecycle == "RESEARCH_QUALIFIED"
                and at > self._qualified
                and at > self._last_at
            )
            if prior:
                direction = self._plan["research_direction"]
                bull = direction == "BULLISH"
                z = self._plan["structural_invalidation"]
                tol = z["break_tolerance"]
                lost = (
                    bar["close"] < z["lower"] - tol
                    if bull
                    else bar["close"] > z["upper"] + tol
                )
                if lost and not any(
                    e["kind"] == "STRUCTURAL_INVALIDATION_OBSERVED"
                    for e in events.values()
                ):
                    add(
                        "STRUCTURAL_INVALIDATION_OBSERVED",
                        [bar["id"], z["zone_id"]],
                        occurred=bar["closed_at"],
                        details=dict(
                            predicate="ORIGINAL_SR_ELIGIBLE_CLOSE_LOSES_FROZEN_ZONE"
                        ),
                    )
                if self._targets and not any(
                    e["kind"] == "STRUCTURAL_TARGET_OBSERVED" for e in events.values()
                ):
                    target = self._targets[0]
                    ohlc = sources[bar["id"]]["ohlc"]
                    contact = (
                        ohlc["high"] >= target["lower"]
                        if bull
                        else ohlc["low"] <= target["upper"]
                    )
                    closed = (
                        bar["close"] > target["upper"] + tol
                        if bull
                        else bar["close"] < target["lower"] - tol
                    )
                    hit = (
                        contact
                        if self._policy.target_observation == "WICK_CONTACT"
                        else closed
                    )
                    if hit:
                        add(
                            "STRUCTURAL_TARGET_OBSERVED",
                            [bar["id"], target["id"]],
                            occurred=(
                                bar["closed_at"]
                                if self._policy.target_observation
                                == "CLOSE_BEYOND_REFERENCE"
                                else None
                            ),
                            interval=(
                                [bar["opened_at"], bar["closed_at"]]
                                if self._policy.target_observation == "WICK_CONTACT"
                                else None
                            ),
                            details=dict(
                                policy=self._policy.target_observation,
                                wick_contact=contact,
                                closed_beyond_reference=closed,
                                not_a_fill=True,
                            ),
                        )
                opposition = set(result["current_opposition"][direction])
                for e in context.evidence:
                    if e.id in opposition:
                        need(
                            e.event_id in sources
                            and sources[e.event_id]["kind"] == "CHOCH_EVENT",
                            "E2_CANONICAL_OPPOSITION_REQUIRED",
                        )
                        add(
                            "OPPOSING_STRUCTURE_OBSERVED",
                            [e.id, e.event_id],
                            event_id=e.event_id,
                            interval=[e.observed_at, e.available_at],
                            details=dict(
                                original_direction=direction,
                                opposing_direction=e.direction,
                                source_event_available_at_utc=e.available_at,
                                break_policy=e.details["confirmation_policy"],
                            ),
                        )
                plan = next(
                    p
                    for p in current["plans"]
                    if p["setup_id"] == self._plan["setup_id"]
                )
                if plan["research_state"] == "EXPIRED":
                    add(
                        "HYPOTHESIS_EXPIRED",
                        [bar["id"]],
                        occurred=bar["closed_at"],
                        details=dict(
                            scope="FIVE_ELIGIBLE_CLOSES_NOT_POSITION_HOLDING_TIME"
                        ),
                    )
            need(len(events) <= LIMITS["max_events"], "E2_EVENT_RESOURCE_LIMIT")
            report = self._report(
                current,
                sorted(events.values(), key=lambda e: (e["available_at_utc"], e["id"])),
                gap,
            )
            need(
                report["sha256"] in self._produced
                or len(self._produced) < LIMITS["max_reports"],
                "E2_REPORT_RESOURCE_LIMIT",
            )
            self._entry = candidate
            self._events = events
            self._gap = gap
            self._last_at = at
            self._lifecycle = report["original_hypothesis_lifecycle"]["state"]
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
            self._last = blocked_exit(
                str(exc)
                if isinstance(exc, ExitInputError)
                else "E2_CURRENT_BINDING_INVALID"
            )
        return deepcopy(self._last)

    def report(self):
        return deepcopy(self._last)


def validate_exit_report(report, *, source=None):
    try:
        need(
            type(report) is dict and set(report) == set(blocked_exit()),
            "E2_REPORT_SCHEMA_INVALID",
        )
        need(
            type(report["report_version"]) is int
            and report["report_version"] == 1
            and report["model_version"] == MODEL,
            "E2_REPORT_VERSION_INVALID",
        )
        need(
            report["sha256"]
            == digest({k: v for k, v in report.items() if k != "sha256"}),
            "E2_REPORT_CHECKSUM_INVALID",
        )
        for k, v in SAFETY.items():
            need(
                type(report[k]) is type(v) and report[k] == v,
                "E2_REPORT_SAFETY_INVALID",
            )
        if report["source_eligibility"] == "VALID":
            need(
                type(source) is ExitResearchSession
                and report["sha256"] in source._produced,
                "E2_PRODUCING_SESSION_REQUIRED",
            )
        else:
            need(report["source_eligibility"] == "BLOCKED", "E2_ELIGIBILITY_INVALID")
            need(
                report == blocked_exit(report["reason_codes"][0]),
                "E2_BLOCKED_HAS_OBSERVATIONS",
            )
    except (
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OverflowError,
        RecursionError,
    ):
        raise ValueError("E2_REPORT_SCHEMA_INVALID") from None
    return True
