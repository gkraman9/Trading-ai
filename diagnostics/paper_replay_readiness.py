"""Offline E4.7 evidence inspection only; never starts historical/live paper trading."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.evidence import AtomicEvidence
from iat.paper_readiness import historical_paper_preflight
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import read_bytes
from hashlib import sha256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--review")
    parser.add_argument("--paper-bundle")
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args(argv)
    hashes = []
    for path in (args.manifest, args.review, args.paper_bundle):
        try:
            hashes.append(sha256(read_bytes(path)).hexdigest() if path else None)
        except (ValueError, OSError):
            hashes.append("UNAVAILABLE")
    run_id = digest(hashes)

    def envelope(value):
        value.pop("sha256", None)
        value.update(run_id=run_id, safety=dict(signal="WAIT", execution_allowed=False))
        return dict(value, sha256=digest(value))

    def validate(value):
        if (
            value.get("status") not in ("BLOCKED", "FAIL")
            or value.get("execution_allowed") is not False
            or value.get("signal") != "WAIT"
            or value.get("historical_validation") != "PENDING"
            or value.get("historical_comparisons") != "NOT_RUN"
            or value.get("sha256")
            != digest({k: v for k, v in value.items() if k != "sha256"})
        ):
            raise ValueError("PAPER_READINESS_PUBLICATION_INVALID")

    initial = historical_paper_preflight()
    initial.update(status="FAIL", reason_codes=["RUN_INCOMPLETE"])
    initial = envelope(initial)
    try:
        writer = AtomicEvidence(args.report_path, initial, validator=validate)
    except (OSError, ValueError):
        print("BLOCKED: use a new report path in a separate output directory.")
        return 1
    try:
        final = envelope(
            historical_paper_preflight(args.manifest, args.review, args.paper_bundle)
        )
        writer.publish(final)
    except (ValueError, TypeError, OSError, KeyError):
        print(
            "BLOCKED: evidence inspection failed; reserved report remains incomplete. Check local inputs."
        )
        return 1
    print("BLOCKED: " + ", ".join(final["reason_codes"]))
    print("Historical validation PENDING; comparisons NOT_RUN; no replay performed.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
