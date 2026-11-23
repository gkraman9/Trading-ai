"""One offline verification operation; never substitutes fixtures or qualifies data."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.boundary_reproduction import verify, START, END


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("m1", "m5", "original-report", "calendar", "output-directory"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--start-utc", default=START)
    p.add_argument("--end-utc", default=END)
    a = p.parse_args(argv)
    try:
        r = verify(
            a.m1,
            a.m5,
            a.original_report,
            a.calendar,
            a.output_directory,
            start=a.start_utc,
            end=a.end_utc,
        )
    except Exception:
        print(
            "BLOCKED: use readable local files, explicit UTC and a NEW private output directory outside Git. No completed evidence summary is claimed."
        )
        return 2
    print("Evidence status: " + r["status"])
    print("Reason codes: " + (", ".join(r["reason_codes"]) or "NONE"))
    print(
        "Research only: WAIT; execution_allowed=false; DATA_NOT_QUALIFIED; Exness BLOCKED; historical validation PENDING."
    )
    return 2 if r["status"] == "BLOCKED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
