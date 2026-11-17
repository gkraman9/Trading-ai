"""Check committed provenance metadata bytes; optionally repair stale CRLF checkouts.

This is repository maintenance, never an evidence/data normalization operation.
Only the five named committed metadata files are eligible for restoration.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CATALOG = 'docs/source_reviews/provenance-gap-analysis-v1/available-sources.json'
METADATA = (
    'docs/source_reviews/xauusd-pilot.manifest.json',
    'docs/source_reviews/xauusd-pilot-review.json',
    'docs/source_reviews/source-qualification-2026-11-14.json',
    'config/examples/historical-evidence/operator-reported-v1.json',
    'config/examples/historical-evidence/operator-manifest-v1.json',
)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def check_metadata(root=ROOT, *, refresh=False):
    """Verify actual bytes against HEAD inventory; never accept normalized hashes."""
    root = Path(root).resolve()
    catalog = json.loads(git(root, 'show', 'HEAD:' + CATALOG))
    if json.loads((root / CATALOG).read_bytes()) != catalog:
        raise ValueError('Inventory differs from HEAD; review local changes first.')
    refs = catalog['metadata_references']
    if len(refs) != len(METADATA) or {r['path'] for r in refs} != set(METADATA):
        raise ValueError('Unexpected metadata scope; no files will be refreshed.')
    # Never overwrite a staged change, even if its working copy is a CRLF variant.
    git(root, 'diff', '--cached', '--exit-code', '--', CATALOG, *METADATA)
    pending = []
    for ref in refs:
        name = ref['path']
        path = root / name
        if path.resolve() != path or not path.is_file():
            raise ValueError('Metadata must be regular repository files: ' + name)
        blob = git(root, 'show', 'HEAD:' + name)
        if sha256(blob).hexdigest() != ref['file_sha256']:
            raise ValueError('HEAD blob does not match inventory: ' + name)
        actual = path.read_bytes()
        if sha256(actual).hexdigest() == ref['file_sha256']:
            continue
        # Diagnose a known checkout conversion, not arbitrary evidence content.
        if b'\r' in blob or actual != blob.replace(b'\n', b'\r\n'):
            raise ValueError('Content mismatch; refusing restoration: ' + name)
        pending.append((path, blob, actual))
    if pending and not refresh:
        raise ValueError('Stale CRLF checkout: ' + ', '.join(str(p.relative_to(root)) for p, _, _ in pending)
                         + '. Review changes, then rerun with --refresh-checkout.')
    for path, blob, original in pending:
        if path.read_bytes() != original:
            raise ValueError('File changed during inspection; rerun after review.')
        # Publish exact verified Git bytes atomically; do not use text-mode IO.
        fd, temporary = tempfile.mkstemp(prefix='.iat-metadata-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(blob)
            os.chmod(temporary, path.stat().st_mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    for ref in refs:
        if sha256((root / ref['path']).read_bytes()).hexdigest() != ref['file_sha256']:
            raise ValueError('Post-refresh SHA-256 mismatch: ' + ref['path'])
    return len(pending)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-checkout', action='store_true',
                        help='Explicitly restore only recognized CRLF variants from verified HEAD blobs.')
    args = parser.parse_args(argv)
    try:
        count = check_metadata(refresh=args.refresh_checkout)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else 'Git/metadata unavailable; check checkout and local changes.'
        print('FAIL: ' + detail)
        return 1
    print('PASS: five committed metadata SHA-256 hashes match; checkout files restored: ' + str(count))
    print('Repository check only. Exness BLOCKED; historical validation PENDING; comparisons NOT_RUN; WAIT; execution disabled.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
