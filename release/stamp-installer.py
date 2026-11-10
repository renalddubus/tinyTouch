#!/usr/bin/env python3
"""Pin the release signing Team ID into a copy of install.sh."""

import os
from pathlib import Path
import re
import sys

PLACEHOLDER = "'__TINYTOUCH_TEAM_ID__'"


def stamp(source: str, team_id: str, *, required: bool) -> str:
    if source.count(PLACEHOLDER) != 1:
        raise SystemExit("install.sh must contain exactly one Team ID placeholder.")
    if not team_id:
        if required:
            raise SystemExit("Published installers require TINYTOUCH_SIGNING_TEAM_ID.")
        return source
    if not re.fullmatch(r"[A-Z0-9]{10}", team_id):
        raise SystemExit("TINYTOUCH_SIGNING_TEAM_ID is not a valid Apple Team ID.")
    return source.replace(PLACEHOLDER, f"'{team_id}'")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: stamp-installer.py SOURCE OUTPUT")
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    stamped = stamp(
        source.read_text(encoding="utf-8"),
        os.environ.get("TINYTOUCH_SIGNING_TEAM_ID", ""),
        required=os.environ.get("TINYTOUCH_REQUIRE_STABLE_IDENTITY") == "1",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(stamped, encoding="utf-8")
    output.chmod(0o755)


if __name__ == "__main__":
    main()
