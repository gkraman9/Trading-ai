"""Private offline Stage-B research. No network, terminal, credentials or orders."""

import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.evidence import AtomicEvidence
from iat.strategy_qualification.dataset import (
    empty_study,
    run_study,
    validate_study,
    run_identifier,
)
from iat.strategy_qualification.specs import specifications
from iat.intelligence.strategy_replay import digest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest")
    p.add_argument("--review")
    p.add_argument("--quote-manifest")
    p.add_argument("--costs")
    p.add_argument("--validation-plan")
    p.add_argument("--continuation-reproduction-review")
    p.add_argument("--sweep-reproduction-review")
    p.add_argument("--report-path", required=True)
    a = p.parse_args(argv)
    reviews = {
        specifications()[0].strategy_id: a.continuation_reproduction_review,
        specifications()[1].strategy_id: a.sweep_reproduction_review,
    }
    report = empty_study()
    report["run_id"] = run_identifier(
        a.manifest, a.review, a.quote_manifest, a.costs, a.validation_plan, reviews
    )
    report["status"] = "FAIL"
    report["reason_codes"] = ["RUN_INCOMPLETE"]
    report["sha256"] = digest(report)
    target = Path(a.report_path)
    repo = Path(__file__).resolve().parents[1]
    try:
        if target.resolve().is_relative_to(repo) or any(
            p.is_symlink() for p in (target, *target.parents)
        ):
            raise ValueError("Private report path required")
        writer = AtomicEvidence(target, report, validator=validate_study)
    except (ValueError, OSError):
        print("BLOCKED: use a NEW private report path outside Git.")
        return 1
    try:
        reviews = {
            specifications()[0].strategy_id: a.continuation_reproduction_review,
            specifications()[1].strategy_id: a.sweep_reproduction_review,
        }
        report = run_study(
            a.manifest, a.review, a.quote_manifest, a.costs, a.validation_plan, reviews
        )
        writer.publish(report)
    except Exception:
        print(
            "BLOCKED: study or report publication failed; preserve RUN_INCOMPLETE evidence."
        )
        return 1
    print(
        "Stage B: " + report["status"] + "; recommendation: " + report["recommendation"]
    )
    print("Stages C/D: BLOCKED_NOT_STARTED; broker orders: 0; execution disabled.")
    return 0 if report["recommendation"] == "PROCEED_TO_STAGE_C_REVIEW_ONLY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
