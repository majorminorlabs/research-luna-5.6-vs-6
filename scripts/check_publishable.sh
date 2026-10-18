#!/bin/sh
# Check staged additions/changes before committing. Install with:
# git config core.hooksPath .githooks
set -eu
cd "$(git rev-parse --show-toplevel)"
exec python3 - <<'PY'
import re
import subprocess
import sys

# Read reviewed research-data exceptions from the index, so unstaged edits
# cannot silently change what this commit allows.
entry = subprocess.run(
    ['git', 'show', ':scripts/publishable-data-paths.txt'],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
)
allowed = set(entry.stdout.splitlines()) if entry.returncode == 0 else set()
paths = subprocess.check_output([
    'git', 'diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z',
]).decode('utf-8', errors='surrogateescape').split('\0')
operational = re.compile(
    r'(?i)(?:^|/)(?:social|_internal|responses|scratch|preview|dist|build|__pycache__)(?:/|$)'
    r'|_internal|handoff|social[-_]drafts|(?:^|/)[^/]*(?:og[-_]share|x[-_]share|reddit[-_]share)[^/]*$'
    r'|\.pyc$'
)
# ARTICLE.md / ARTICLE-METADATA.json and *-METADATA.json belong on the site.
# Keep case-sensitive *-METADATA.json consistent with .gitignore; lowercase
# run-metadata.json files remain frozen scientific run records.
article_files = re.compile(r'(?i)(?:^|/)ARTICLE(?:\.md|-METADATA\.json)$')
publication_metadata = re.compile(r'(?:^|/)[^/]+-METADATA\.json$')
data_names = re.compile(r'(?i)prompt|responses')
blocked = [path for path in paths if path and (
    operational.search(path) or article_files.search(path) or publication_metadata.search(path)
    or (data_names.search(path) and path not in allowed)
)]
if blocked:
    print('Commit rejected: staged files that belong outside research repositories:', file=sys.stderr)
    for path in blocked:
        print('  ' + path, file=sys.stderr)
    print('Keep publication assets on the site. Review scientific-data exceptions explicitly.', file=sys.stderr)
    sys.exit(1)
print('PASS: staged paths are publishable.')
PY
