"""A complete invented file graph. Human verdicts MUST be mocked; never real evidence."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import csv, io, json
from pathlib import Path
from test_evaluation_window import v2_fixture
from test_e47_readiness import schema_bundle
from test_qualification_assistant import export_fixture
from iat.replay_dataset import load_dataset, utc
from iat.e5_protocol import baseline, protocol
from iat.e5_source import BAR_COLUMNS, ASSERTIONS
from iat.paper_readiness import QUOTE_COLUMNS
from iat.intelligence.strategy_replay import digest


def package(root):
    def write(name, obj):
        (root / name).write_bytes(json.dumps(obj).encode())
        return ref(name)

    def ref(name):
        return dict(file=name, sha256=sha256((root / name).read_bytes()).hexdigest())

    def csv_bytes(columns, rows):
        f = io.StringIO(newline="")
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        return f.getvalue().encode()

    # Existing synthetic helpers; no actual independent approval is authored here.
    importpath = export_fixture(root, count=180, warmup=90)
    fullpath = v2_fixture(
        root,
        count=180,
        evaluation_minutes=90,
        historical=True,
        calendar=True,
        origin="NATIVE_SAME_FEED",
    )
    full = json.loads(fullpath.read_text())
    fullpath = root / "outcome-manifest.json"
    fullpath.write_text(json.dumps(full))
    extended = load_dataset(fullpath)
    t0 = utc(full["utc_range"]["start"])
    cut = t0 + timedelta(minutes=175)
    end = t0 + timedelta(minutes=180)
    m = deepcopy(full)
    m["evaluation"]["end"] = m["utc_range"]["end"] = cut.isoformat()
    fields = ["timestamp", "open", "high", "low", "close"]
    for tf, period in (("M1", 1), ("M5", 5)):
        rows = [
            r
            for r in extended.rows[tf]
            if utc(r["timestamp"]) + timedelta(minutes=period) <= cut
        ]
        name = "eval-" + tf + ".csv"
        (root / name).write_bytes(csv_bytes(fields, rows))
        m["frames"][tf] = ref(name)
    evalpath = root / "evaluation-manifest.json"
    evalpath.write_text(json.dumps(m))
    data = load_dataset(evalpath)
    bundle, _ = schema_bundle(root)
    bundle.update(
        feed_id=m["lineage"]["feed_id"],
        dataset_id=digest(data.metadata),
        reviewed_at_utc=(t0 + timedelta(days=2)).isoformat(),
    )
    bundle["windows"] = dict(
        warmup=data.metadata["warmup"],
        evaluation=data.metadata["evaluation"],
        outcome=dict(start=cut.isoformat(), end=end.isoformat()),
    )
    for tf in ("M1", "M5"):
        bundle["artifacts"]["raw_" + tf.lower()] = full["frames"][tf]
    for key in ("specification", "costs"):
        obj = json.loads((root / bundle["artifacts"][key]["file"]).read_bytes())
        obj.update(
            feed_id=bundle["feed_id"],
            available_at_utc=(t0 - timedelta(days=1)).isoformat(),
            effective_from_utc=(t0 - timedelta(days=1)).isoformat(),
            effective_until_utc=(end + timedelta(days=1)).isoformat(),
        )
        bundle["artifacts"][key] = write(key + ".json", obj)
    bundle["artifacts"]["policies"] = write("policies.json", baseline())
    qs = []
    for bar in extended.rows["M1"]:
        at = utc(bar["timestamp"])
        for sec, field in ((0, "open"), (15, "high"), (30, "low"), (45, "close")):
            stamp = (at + timedelta(seconds=sec)).isoformat()
            bid = str(bar[field])
            from decimal import Decimal

            qs.append(
                dict(
                    sequence=str(len(qs)),
                    occurred_at_utc=stamp,
                    available_at_utc=stamp,
                    bid=bid,
                    ask=str(Decimal(bid) + Decimal("0.2")),
                    revision="0",
                    finality="FINAL",
                )
            )
    qs.append(
        dict(
            qs[-1],
            sequence=str(len(qs)),
            occurred_at_utc=end.isoformat(),
            available_at_utc=end.isoformat(),
        )
    )
    (root / "quotes.csv").write_bytes(csv_bytes(QUOTE_COLUMNS, qs))
    bundle["artifacts"]["quote_events"] = ref("quotes.csv")
    for item in bundle["evidence"].values():
        item["scope"] = dict(start=t0.isoformat(), end=end.isoformat())
    bundle_ref = write("paper-bundle.json", bundle)
    spec = json.loads(importpath.read_text())
    spec["dataset_kind"] = "INDEPENDENT_HISTORICAL"
    spec["preparer_code"] = bundle["preparer_code"]
    spec["source"].update(feed_id=bundle["feed_id"])
    for tf, f in spec["frames"].items():
        f.update(
            feed_id=bundle["feed_id"],
            file=full["frames"][tf]["file"],
            volume_kind="NONE",
        )
        f["columns"] = {k: (k if k in fields else None) for k in f["columns"]}
        f["finality"]["policy"] = "DOCUMENTED_CLOSED_EXPORT"
    spec_ref = write("import.json", spec)
    bars = []
    for tf, period in (("M1", 1), ("M5", 5)):
        for bar in extended.rows[tf]:
            close = (utc(bar["timestamp"]) + timedelta(minutes=period)).isoformat()
            bars.append(
                dict(
                    timeframe=tf,
                    opened_at_utc=bar["timestamp"],
                    closed_at_utc=close,
                    available_at_utc=close,
                    revision="0",
                    finality="FINAL",
                )
            )
    (root / "availability.csv").write_bytes(csv_bytes(BAR_COLUMNS, bars))
    review_ref = write(
        "human-review.mock.json",
        dict(
            SYNTHETIC_ONLY="NO_REAL_HUMAN_SIGNOFF",
            reviewer_code="synthetic-independent",
            independent_review_attested=True,
            decision="APPROVED",
            provider_entity=spec["source"]["provider_entity"],
        ),
    )
    plan = dict(
        version=1,
        protocol_sha256=protocol()["sha256"],
        inputs=dict(
            manifest=ref(evalpath.name),
            review=review_ref,
            paper_bundle=bundle_ref,
            outcome_manifest=ref(fullpath.name),
            outcome_review=review_ref,
            import_spec=spec_ref,
            bar_availability=ref("availability.csv"),
        ),
    )
    planpath = root / "plan.json"
    planpath.write_text(json.dumps(plan))
    e = root / "synthetic-evidence.txt"
    r = dict(
        version=1,
        kind="E5_INDEPENDENT_ADAPTER_REVIEW",
        preparer_code=bundle["preparer_code"],
        reviewer_code="synthetic-reviewer",
        independently_reviewed=True,
        decision="APPROVED",
        reviewed_at_utc=bundle["reviewed_at_utc"],
        plan_sha256=sha256(planpath.read_bytes()).hexdigest(),
        protocol_sha256=protocol()["sha256"],
        assertions={
            k: dict(
                status="VERIFIED",
                **ref(e.name),
                scope=dict(start=t0.isoformat(), end=end.isoformat())
            )
            for k in ASSERTIONS
        },
    )
    rpath = root / "adapter-review.mock.json"
    rpath.write_text(json.dumps(r))
    ready = dict(
        input_checks_status="DOCUMENT_AND_MECHANICAL_CHECKS_PASSED",
        reason_codes=[],
        source_qualification=dict(
            dataset_id=digest(data.metadata), human_review_sha256=review_ref["sha256"]
        ),
        sha256=digest("SYNTHETIC_MOCK_GATE_ONLY"),
        bundle_sha256=sha256((root / "paper-bundle.json").read_bytes()).hexdigest(),
        artifacts={k: v["sha256"] for k, v in bundle["artifacts"].items()},
    )
    gate = dict(
        status="HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED",
        dataset_id=digest(extended.metadata),
        human_review_sha256=review_ref["sha256"],
    )
    return planpath, rpath, ready, gate
