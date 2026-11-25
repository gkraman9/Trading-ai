"""Sanitized local environment comparison. No service, journals, login or orders."""

import argparse
import hashlib
import hmac
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.mt5_connection import MT5Connection, package_label


def file_hash(path):
    try:
        if Path(path).stat().st_size > 64 * 1024 * 1024:
            return None
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except (OSError, TypeError):
        return None


def probe(*, inspect_only=False, nonce=None, loader=None):
    result = dict(
        probe_version=1,
        python=".".join(map(str, sys.version_info[:3])),
        architecture_bits=struct.calcsize("P") * 8,
        executable_sha256=file_hash(sys.executable),
        mt5_package=None,
        mt5_module_sha256=None,
        attachment_token=None,
        connection=None,
        attachment_attempted=False,
        acquisition="NOT_RUN",
        signal="WAIT",
        execution_allowed=False,
        exness="BLOCKED",
        qualification="DATA_NOT_QUALIFIED",
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
        mode="READ_ONLY_SHADOW",
    )
    try:
        result["mt5_package"] = package_label(version("MetaTrader5"))
    except PackageNotFoundError:
        pass
    if inspect_only:
        return result

    def capture():
        if loader is None:
            from importlib import import_module

            module = import_module("MetaTrader5")
        else:
            module = loader()
        result["mt5_module_sha256"] = file_hash(getattr(module, "__file__", None))
        return module

    p = MT5Connection(capture)
    result["attachment_attempted"] = True
    try:
        p.preflight()
        # Same serialized owner, no names/paths retained in the output.
        info = p._call(p._reader._terminal)
        path = getattr(info, "path", None)
        if type(nonce) is str and len(nonce) == 32 and type(path) is str:
            result["attachment_token"] = hmac.new(
                nonce.encode(),
                str(Path(path).resolve()).casefold().encode(),
                hashlib.sha256,
            ).hexdigest()
        result["mt5_package"] = p.snapshot()["runtime"]["mt5_package"]
    except Exception:
        pass  # Only allowlisted manager state is evidence; never exception text.
    finally:
        result["connection"] = p.snapshot()
        p.close_owner()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--comparison-nonce")
    args = parser.parse_args(argv)
    if not args.inspect_only and (
        sys.platform != "win32" or sys.version_info[:2] != (3, 11)
    ):
        parser.error(
            "Attachment requires Windows Python 3.11; use --inspect-only otherwise"
        )
    print(
        json.dumps(
            probe(inspect_only=args.inspect_only, nonce=args.comparison_nonce),
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
