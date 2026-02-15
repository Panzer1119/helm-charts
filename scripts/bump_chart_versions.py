#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path
import semver


DEFAULT_POLICY = "minor-or-patch"


def strip_suffix(version: str) -> str:
    return re.split(r"[-@]", version)[0]


def read_version_line(text: str) -> str | None:
    m = re.search(r"^version:\s*([^\s#]+)", text, re.MULTILINE)
    return m.group(1) if m else None


def replace_version_line(text: str, new_version: str) -> str:
    return re.sub(
        r"^(version:\s*)([^\s#]+)",
        r"\g<1>" + new_version,
        text,
        count=1,
        flags=re.MULTILINE,
    )


def read_policy(text: str) -> str:
    m = re.search(
        r"renovate\.appVersionPolicy:\s*['\"]?([a-z\-]+)",
        text,
        re.IGNORECASE,
    )
    return m.group(1).lower() if m else DEFAULT_POLICY


def decide_bump(old_chart, old_app, new_app, policy):
    try:
        old_app_v = semver.VersionInfo.parse(strip_suffix(old_app))
        new_app_v = semver.VersionInfo.parse(strip_suffix(new_app))
        chart_v = semver.VersionInfo.parse(old_chart)
    except ValueError:
        return None

    if new_app_v.major != old_app_v.major:
        return None

    if policy == "ignore":
        return None

    if new_app_v.minor != old_app_v.minor:
        if policy in ("minor-or-patch", "minor-only"):
            return str(chart_v.bump_minor())

    if new_app_v.patch != old_app_v.patch:
        if policy in ("minor-or-patch", "patch-only"):
            return str(chart_v.bump_patch())

    return None


def main():
    changes = json.load(sys.stdin)
    changed_any = False

    for entry in changes:
        path = Path(entry["path"])
        old_app = entry["old_app"]
        new_app = entry["new_app"]

        text = path.read_text()
        old_chart = read_version_line(text)
        policy = read_policy(text)

        if not old_chart:
            continue

        new_chart = decide_bump(old_chart, old_app, new_app, policy)

        if new_chart:
            print(
                f"{path}: policy={policy}, "
                f"appVersion {old_app}→{new_app}, "
                f"chart {old_chart}→{new_chart}"
            )
            path.write_text(replace_version_line(text, new_chart))
            changed_any = True

    if not changed_any:
        print("No chart versions changed.")


if __name__ == "__main__":
    main()