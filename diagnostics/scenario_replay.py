"""Offline scenario replay. Full reports embed private source files: keep them local."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.replay_dataset import read_bytes, strict_json
from iat.chart_benchmark import write_new
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.scenario_replay import MODES, run_scenario_replay, validate_scenario_replay


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    parser.add_argument('--mode', choices=MODES, default='SYNTHETIC_RESEARCH')
    parser.add_argument('--review')
    parser.add_argument('--cutoff-utc')
    parser.add_argument('--observations', help='Local JSON array of UTC M1 close timestamps')
    parser.add_argument('--context-config')
    parser.add_argument('--intelligence-config')
    parser.add_argument('--report-path', required=True, help='New private local JSON file; never overwritten')
    args = parser.parse_args(argv)
    try:
        context = ContextConfig.from_dict(strict_json(read_bytes(args.context_config))) if args.context_config else None
        intelligence = IntelligenceConfig.from_dict(strict_json(read_bytes(args.intelligence_config))) if args.intelligence_config else None
        observations = strict_json(read_bytes(args.observations)) if args.observations else None
        report = run_scenario_replay(args.manifest, mode=args.mode, review_path=args.review,
            config=context, intelligence_config=intelligence, observation_times=observations, cutoff_utc=args.cutoff_utc)
        validate_scenario_replay(report)
        write_new(args.report_path, report)
    except (ValueError, TypeError, KeyError, OSError, OverflowError):
        print('FAIL: REPLAY_INPUT_OR_PUBLICATION_INVALID. Check local manifest, configurations and use a new output filename.')
        return 1
    print('Status: ' + report['status'])
    print('Historical validation: PENDING; historical comparisons: NOT_RUN')
    print('Snapshots: ' + str(report['summary']['all']['snapshots']))
    print('Private report written; do not upload embedded source files.')
    return 0 if report['status'] == 'COMPLETED' else 3


if __name__ == '__main__':
    raise SystemExit(main())
