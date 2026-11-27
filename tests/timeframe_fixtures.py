"""Explicitly invented R1 source/evidence packets, never broker market evidence."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from iat.timeframes import (
    EvidenceDocument,
    EvidenceStore,
    FrameBinding,
    TimeframeProfile,
    FrameName,
    FIXED_SECONDS,
    canonical,
)

START = datetime(2026, 11, 12, tzinfo=timezone.utc)
BEGIN = "2026-11-01T00:00:00+00:00"
END = "2026-12-01T00:00:00+00:00"


def document(kind, claims, available="2026-10-01T00:00:00+00:00"):
    return EvidenceDocument(
        canonical(dict(version=1, kind=kind, available_at_utc=available, claims=claims))
    )


def phase(start=BEGIN, end=END, quotes="OPEN", positions="ALLOWED"):
    return dict(
        start_utc=start, end_utc=end, quotations=quotes, new_positions=positions
    )


def fixture(
    frame="M15",
    *,
    n=3,
    window=START,
    phases=None,
    source=None,
    interval=None,
    calendar=None,
    finality=None,
    available=None,
    required=3,
    max_slots=10000
):
    name = FrameName(frame)
    s = document(
        "SOURCE",
        dict(
            provider="INVENTED_PROVIDER",
            feed="INVENTED_FEED",
            symbol="XAUUSD",
            price_basis="BID",
            provenance="SYNTHETIC_FIXTURE",
            source_revision="SYNTHETIC_V1",
            **{}
        )
        | (source or {}),
    )
    i = document(
        "INTERVAL",
        dict(
            source_sha256=s.sha256,
            frame=frame,
            provider_frame=frame,
            mapping="FIXED_UTC_GRID_V1",
            duration_seconds=FIXED_SECONDS[name],
            anchor_utc=BEGIN,
            grid_timezone="UTC",
            valid_from_utc=BEGIN,
            valid_until_utc=END,
            bar_policy="FULL_QUOTATION_INTERVALS_ONLY",
        )
        | (interval or {}),
        available or "2026-10-01T00:00:00+00:00",
    )
    c = document(
        "CALENDAR",
        dict(
            source_sha256=s.sha256,
            coverage_start_utc=BEGIN,
            coverage_end_utc=END,
            phases=phases or [phase()],
        )
        | (calendar or {}),
    )
    f = document(
        "FINALITY",
        dict(
            source_sha256=s.sha256,
            interval_sha256=i.sha256,
            policy="EXPLICIT_FINAL_CLOSE_AND_AVAILABILITY",
            correction_policy="REVISION_BOUND_NO_RETROSPECTIVE_REWRITE",
        )
        | (finality or {}),
    )
    store = EvidenceStore((s, i, c, f))
    binding = FrameBinding(
        name, s.sha256, i.sha256, c.sha256, f.sha256, required, max_slots
    )
    profile = TimeframeProfile((binding,))
    rows = []
    for index in range(n):
        a = window + timedelta(seconds=index * FIXED_SECONDS[name])
        b = a + timedelta(seconds=FIXED_SECONDS[name])
        rows.append(
            dict(
                frame=frame,
                provider_frame=frame,
                provider="INVENTED_PROVIDER",
                feed="INVENTED_FEED",
                symbol="XAUUSD",
                price_basis=(source or {}).get("price_basis", "BID"),
                source_sha256=s.sha256,
                opened_at_utc=a.isoformat(),
                closed_at_utc=b.isoformat(),
                available_at_utc=b.isoformat(),
                finality="FINAL",
                revision=0,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
            )
        )
    return dict(
        profile=profile,
        evidence=store,
        frame=frame,
        rows=rows,
        window_start_utc=window.isoformat(),
        as_of_utc=(window + timedelta(seconds=n * FIXED_SECONDS[name])).isoformat(),
    )
