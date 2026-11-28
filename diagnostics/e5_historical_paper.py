"""Offline E5 file-bound adapter. No MT5, credentials, network or live paper service."""

import argparse
from pathlib import Path
import sys
from hashlib import sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.e5_replay import run_historical, empty_report
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import read_bytes
from iat.evidence import AtomicEvidence


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan")
    p.add_argument("--independent-review")
    p.add_argument("--prefix-cutoff")
    p.add_argument("--report-path", required=True)
    args = p.parse_args(argv)
    hashes = []
    for path in (args.plan, args.independent_review):
        try:
            hashes.append(sha256(read_bytes(path)).hexdigest() if path else None)
        except (ValueError, OSError):
            hashes.append("UNAVAILABLE")
    run_id = digest([hashes, args.prefix_cutoff])

    def wrap(r):
        r.pop("sha256", None)
        r.update(run_id=run_id, safety=dict(signal="WAIT", execution_allowed=False))
        return dict(r, sha256=digest(r))

    def validate(r):
        if (
            r["status"] not in ("FAIL", "BLOCKED", "PASS")
            or r["execution_allowed"] is not False
            or r["signal"] != "WAIT"
            or r["exness"] != "BLOCKED"
            or r["historical_validation"] != "PENDING"
            or r["sha256"] != digest({k: v for k, v in r.items() if k != "sha256"})
            or r["status"] != "PASS"
            and r["historical_metrics"] is not None
        ):
            raise ValueError("E5_PUBLICATION_INVALID")

    initial = empty_report()
    initial.update(status="FAIL", reason_codes=["RUN_INCOMPLETE"])
    try:
        writer = AtomicEvidence(args.report_path, wrap(initial), validator=validate)
    except (ValueError, OSError):
        print("BLOCKED: use a new report path in an existing private output directory.")
        return 1
    try:
        result = wrap(
            run_historical(
                args.plan, args.independent_review, prefix_cutoff=args.prefix_cutoff
            )
        )
        writer.publish(result)
    except (ValueError, TypeError, KeyError, OSError):
        print("FAIL: E5 publication incomplete; no success report was left.")
        return 1
    print("E5 " + result["status"] + ": " + ", ".join(result["reason_codes"]))
    print(
        "Performance: " + result["performance_status"] + "; WAIT; execution disabled."
    )
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
