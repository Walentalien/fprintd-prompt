"""Compare the utility's prompt identifiers with a downloaded upstream header."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fprintd_prompt as fp


def initial_msgids(source: str) -> list[str]:
    table = re.search(r"\bfingers\s*\[\s*\]\s*=\s*\{(.*?)\n\};", source, re.S)
    if table is None:
        raise ValueError("Cannot locate the upstream fingers table.")
    strings = re.findall(r'N_\("((?:[^"\\]|\\.)*)"\)', table.group(1))
    msgids = [json.loads('"' + text + '"') for text in strings]
    if not msgids or len(msgids) != len(set(msgids)):
        raise ValueError("Upstream prompt identifiers are empty or duplicated.")
    return msgids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("header", type=Path)
    args = parser.parse_args(argv)
    try:
        upstream = set(initial_msgids(args.header.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    supported = set(fp.INITIAL_MSGIDS)
    for msgid in sorted(upstream - supported):
        print(f"Unsupported upstream prompt: {msgid}", file=sys.stderr)
    for msgid in sorted(supported - upstream):
        print(f"Prompt no longer in upstream: {msgid}", file=sys.stderr)
    if upstream != supported:
        return 1
    print(f"All {len(upstream)} upstream prompt identifiers match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
