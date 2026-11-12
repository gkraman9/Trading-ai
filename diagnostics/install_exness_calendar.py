"""Offline reviewed-candidate installer; no MT5 access and no approval bypass."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.exness_profile import inspect_profile, install_profile


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('Invalid installer arguments')


def main(argv=None):
    parser = SafeParser(description='Install or inspect the runtime-blocked Exness calendar candidate')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--inspect', action='store_true')
    choice.add_argument('--destination')
    parser.add_argument('--replace-confirmed', action='store_true')
    parser.add_argument('--expected-current-sha256')
    try:
        args = parser.parse_args(argv)
        if args.inspect and (args.replace_confirmed or args.expected_current_sha256 is not None):
            raise ValueError('Inspection cannot replace files')
        result = inspect_profile() if args.inspect else install_profile(args.destination,
                     replace_confirmed=args.replace_confirmed,
                     expected_current_sha256=args.expected_current_sha256)
        print(json.dumps(result, indent=2))
        return 2  # Successfully inspected/installed, but assurance is BLOCKED.
    except FileExistsError:
        print(json.dumps({'status': 'FAIL', 'code': 'EXISTING_CONFIG_CONFIRMATION_REQUIRED',
                          'signal': 'WAIT', 'execution_allowed': False}))
        return 1
    except Exception:
        print(json.dumps({'status': 'FAIL', 'code': 'PROFILE_INSTALLATION_FAILED',
                          'signal': 'WAIT', 'execution_allowed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
