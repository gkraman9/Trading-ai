"""Private local diagnostics of a PR #28 replay; never uploads or prints source contents."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.chart_benchmark import read_json, write_new
from iat.replay_diagnostics import generate_replay_diagnostics, validate_replay_diagnostics, diagnostics_text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-report', required=True)
    parser.add_argument('--json-output', required=True)
    parser.add_argument('--text-output', required=True)
    args = parser.parse_args(argv)
    try:
        paths = [Path(p).resolve() for p in (args.replay_report, args.json_output, args.text_output)]
        if len(set(paths)) != 3 or any(p.exists() for p in paths[1:]):
            raise ValueError('New distinct output paths required')
        replay = read_json(paths[0])  # Contains private embedded source files; never printed or re-exported.
        report = generate_replay_diagnostics(replay)
        validate_replay_diagnostics(report, replay)
        summary = diagnostics_text(report)
        write_new(paths[1], report)
        write_new(paths[2], summary)
    except (ValueError, TypeError, KeyError, OSError, OverflowError):
        print('FAIL: INVALID_REPLAY_OR_PRIVATE_EXPORT. Verify the replay and use distinct new local output filenames.')
        return 1
    print('PRIVATE diagnostics created. Observations: ' + str(report['observation_count']))
    print('WAIT; execution disabled; historical validation PENDING; comparisons NOT_RUN.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
