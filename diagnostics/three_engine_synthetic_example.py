"""Generate explicit SYNTHETIC research data and a reproducible three-engine journal."""

import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.three_engine.example import run


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-directory", required=True)
    a = p.parse_args(argv)
    try:
        report, _ = run(a.output_directory)
        print(
            "SYNTHETIC ONLY; comparison replay "
            + report["verification"]["status"]
            + "; actual AI calls 0; broker orders 0."
        )
        return 0
    except Exception:
        print(
            "BLOCKED: use a NEW private directory outside Git. No existing evidence is overwritten."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
