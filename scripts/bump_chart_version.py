#!/usr/bin/env python3
"""Decide whether a Helm chart version should be bumped from appVersion changes.

Policy lookup order in Chart.yaml:
1) top-level key: renovate.appVersionPolicy
2) nested key: renovate.appVersionPolicy

Supported policy formats:
- Preset string:
  - default       -> major:minor, minor:minor, patch:patch, prerelease:none, build:none, digest:none, downgrade:none, unknown:none
  - mirror        -> major:major, minor:minor, patch:patch, prerelease:none, build:none, digest:none, downgrade:none, unknown:none
  - ignore-major  -> major:none,  minor:minor, patch:patch, prerelease:none, build:none, digest:none, downgrade:none, unknown:none
- Mapping (YAML object), for example:
  renovate:
    appVersionPolicy:
      major: major
      minor: patch
      patch: patch
      prerelease: none
      build: none
      digest: none
      downgrade: none
      unknown: none
- Assignment string, for example:
  renovate.appVersionPolicy: "major=major,minor=minor,patch=patch,prerelease=none,build=none,digest=none,downgrade=none,unknown=none"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
import semver

VersionPart = Literal["major", "minor", "patch"]
ExtendedVersionPart = VersionPart | Literal["prerelease", "build", "digest"]

AppChange = ExtendedVersionPart | Literal["none", "downgrade", "unknown"]
ChartBump = VersionPart | Literal["none"]

PRESET_POLICIES: dict[str, dict[AppChange, ChartBump]] = {
    "default": {"major": "minor", "minor": "minor", "patch": "patch", "prerelease": "none", "build": "none",
                "digest": "none", "downgrade": "none", "unknown": "none"},
    "mirror": {"major": "major", "minor": "minor", "patch": "patch", "prerelease": "none", "build": "none",
               "digest": "none", "downgrade": "none", "unknown": "none"},
    "ignore-major": {"major": "none", "minor": "minor", "patch": "patch", "prerelease": "none", "build": "none",
                     "digest": "none", "downgrade": "none", "unknown": "none"},
}
DEFAULT_POLICY: dict[AppChange, ChartBump] = PRESET_POLICIES["default"]


@dataclass(frozen=True)
class Decision:
    should_bump: bool
    app_change: AppChange
    chart_bump: ChartBump
    old_chart_version: str
    new_chart_version: str
    old_app_version: str
    new_app_version: str
    reason: str


@dataclass(frozen=True)
class ParsedAppVersion:
    version: semver.Version
    digest_suffix: str | None = None

    def __str__(self) -> str:
        if self.digest_suffix:
            return f"{self.version}@{self.digest_suffix}"
        return f"{self.version}"


def parse_semver(version: str, optional_minor_and_patch: bool) -> semver.Version:
    """Parse semver with library validation and a consistent error message."""
    try:
        return semver.Version.parse(
            version.strip(),
            optional_minor_and_patch=optional_minor_and_patch,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid semver version: {version!r}") from exc


def parse_app_version(version: str, optional_minor_and_patch: bool) -> ParsedAppVersion:
    """Parse appVersion with optional @sha256 digest suffix."""
    raw = version.strip()
    digest_suffix: str | None = None
    semver_part = raw

    digest_match = re.search(r"@(sha256:[0-9a-fA-F]{64})$", raw)
    if digest_match:
        digest_suffix = digest_match.group(1)
        semver_part = raw[:digest_match.start()]

    # Common chart/app tags use a leading "v" (for example v1.2.3).
    if semver_part.startswith(("v", "V")):
        semver_part = semver_part[1:]

    parsed = parse_semver(semver_part, optional_minor_and_patch=optional_minor_and_patch)
    return ParsedAppVersion(version=parsed, digest_suffix=digest_suffix)


def detect_app_change(old_version: ParsedAppVersion, new_version: ParsedAppVersion) -> AppChange:
    """Classify appVersion change level from old -> new."""

    if new_version.version < old_version.version:
        return "downgrade"
    elif new_version == old_version:
        return "none"
    elif new_version.version.major != old_version.version.major:
        return "major"
    elif new_version.version.minor != old_version.version.minor:
        return "minor"
    elif new_version.version.patch != old_version.version.patch:
        return "patch"
    elif new_version.version.prerelease != old_version.version.prerelease:
        return "prerelease"
    elif new_version.version.build != old_version.version.build:
        return "build"
    elif new_version.digest_suffix != old_version.digest_suffix:
        return "digest"
    else:
        return "unknown"


def bump_semver(version: semver.Version, bump: ChartBump) -> semver.Version:
    """Return bumped semver for major/minor/patch/none."""
    if bump == "none":
        return version
    if bump == "patch":
        return version.bump_patch()
    if bump == "minor":
        return version.bump_minor()
    if bump == "major":
        return version.bump_major()

    raise ValueError(f"Unsupported bump type: {bump!r}")


def read_chart_file(chart_path: Path) -> dict[str, Any]:
    """Read Chart.yaml content as mapping."""
    try:
        content = chart_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read chart file {chart_path}: {exc}") from exc

    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {chart_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level mapping in {chart_path}")
    return data


def replace_version_line(content: str, new_version: str) -> str:
    """Replace the first top-level `version:` line while preserving formatting."""
    version_line_re = re.compile(
        r"^(?P<key>version)(?P<sep>\s*:\s*)(?P<quote>['\"]?)(?P<value>[^\n#'\"]*)(?P=quote)(?P<tail>\s*(?:#.*)?)$",
        flags=re.MULTILINE,
    )

    def _replace(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return (
            f"{match.group('key')}{match.group('sep')}"
            f"{quote}{new_version}{quote}{match.group('tail')}"
        )

    updated, count = version_line_re.subn(_replace, content, count=1)
    if count == 0:
        raise ValueError("Could not find top-level 'version:' line in Chart.yaml")
    return updated


def update_chart_version_in_place(chart_path: Path, new_version: str) -> bool:
    """Update chart version inline without YAML reserialization; returns True if changed."""
    try:
        content = chart_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read chart file {chart_path}: {exc}") from exc

    updated = replace_version_line(content, new_version)
    if updated == content:
        return False

    try:
        chart_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to write chart file {chart_path}: {exc}") from exc
    return True


def get_policy_value(chart_data: dict[str, Any]) -> Any:
    """Extract policy from either dotted or nested key."""
    if "renovate.appVersionPolicy" in chart_data:
        return chart_data["renovate.appVersionPolicy"]

    renovate = chart_data.get("renovate")
    if isinstance(renovate, dict) and "appVersionPolicy" in renovate:
        return renovate["appVersionPolicy"]

    return None


def normalize_policy_bump(value: Any, key: AppChange) -> ChartBump:
    """Normalize one policy bump value."""
    if not isinstance(value, str):
        raise ValueError(f"Policy key '{key}' must be a string")

    lowered = value.strip().lower()
    if lowered in {"none", "patch", "minor", "major"}:
        return lowered  # type: ignore[return-value]

    raise ValueError(
        f"Invalid bump value for '{key}': {value!r}. "
        "Expected one of: none, patch, minor, major"
    )


def parse_assignment_policy(raw: str) -> dict[AppChange, ChartBump]:
    """Parse policy string like: major=major,minor=minor,patch=patch."""
    mapping: dict[AppChange, ChartBump] = dict(DEFAULT_POLICY)
    parts = [part.strip() for part in raw.split(",") if part.strip()]

    for part in parts:
        if "=" not in part:
            raise ValueError(
                f"Invalid policy token {part!r}; expected format key=value"
            )
        key, value = [piece.strip().lower() for piece in part.split("=", 1)]
        if key not in {"major", "minor", "patch", "prerelease", "build", "digest", "downgrade", "unknown"}:
            raise ValueError(
                f"Invalid policy key {key!r}; expected one of: major, minor, patch, prerelease, build, digest, downgrade, unknown"
            )
        mapping[key] = normalize_policy_bump(value, key)

    return mapping


def resolve_policy(raw_policy: Any) -> dict[AppChange, ChartBump]:
    """Resolve policy from chart field into normalized mapping."""
    if raw_policy is None:
        return dict(DEFAULT_POLICY)

    if isinstance(raw_policy, str):
        raw = raw_policy.strip().lower()
        if raw in PRESET_POLICIES:
            return dict(PRESET_POLICIES[raw])
        return parse_assignment_policy(raw_policy)

    if isinstance(raw_policy, dict):
        result = dict(DEFAULT_POLICY)
        for key in ("major", "minor", "patch", "prerelease", "build", "digest", "downgrade", "unknown"):
            if key in raw_policy:
                result[key] = normalize_policy_bump(raw_policy[key], key)
        return result

    raise ValueError(
        "Invalid renovate.appVersionPolicy type. "
        "Expected string or mapping"
    )


def decide_chart_version(
        old_app_version: ParsedAppVersion,
        new_app_version: ParsedAppVersion,
        old_chart_version: semver.Version,
        policy: dict[AppChange, ChartBump],
) -> Decision:
    """Compute bump decision from old/new app versions and policy."""
    app_change: AppChange = detect_app_change(old_app_version, new_app_version)

    if app_change in {"none", "downgrade"}:
        chart_bump: ChartBump = "none"
        reason: str = (
            "App version did not increase"
            if app_change == "none"
            else "App version downgrade detected"
        )
    else:
        chart_bump: ChartBump = policy[app_change]
        reason: str = (
            "Policy maps appVersion change to no chart bump"
            if chart_bump == "none"
            else "Policy requires chart version bump"
        )

    new_chart_version: semver.Version = bump_semver(old_chart_version, chart_bump)

    return Decision(
        should_bump=chart_bump != "none",
        app_change=app_change,
        chart_bump=chart_bump,
        old_chart_version=str(old_chart_version),
        new_chart_version=str(new_chart_version),
        old_app_version=str(old_app_version),
        new_app_version=str(new_app_version),
        reason=reason,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Decide whether Helm Chart.yaml version should be bumped based on "
            "appVersion and renovate.appVersionPolicy"
        )
    )
    parser.add_argument("chart_path", type=Path, help="Path to Chart.yaml")
    parser.add_argument("old_app_version", help="Previous appVersion (semver)")
    parser.add_argument("old_chart_version", help="Previous chart version (semver)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )
    parser.add_argument(
        "--optional-minor-and-patch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Allow parsing shorthand semver forms (for example 1 or 1.2). "
            "Use --no-optional-minor-and-patch for strict major.minor.patch."
        ),
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="If a bump is required, update Chart.yaml version inline using regex replacement.",
    )
    return parser


def format_text_output(decision: Decision) -> str:
    status = "BUMP" if decision.should_bump else "NO_BUMP"
    return (
        f"{status}: app {decision.old_app_version} -> {decision.new_app_version} "
        f"({decision.app_change}), chart {decision.old_chart_version} -> "
        f"{decision.new_chart_version} ({decision.chart_bump}); {decision.reason}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        chart_data: dict[str, Any] = read_chart_file(args.chart_path)

        new_app_version: Any | None = chart_data.get("appVersion")
        if not isinstance(new_app_version, str) or not new_app_version.strip():
            raise ValueError("Chart.yaml must include a non-empty string appVersion")

        old_chart_version: semver.Version = parse_semver(
            args.old_chart_version,
            optional_minor_and_patch=args.optional_minor_and_patch,
        )
        old_app_version: ParsedAppVersion = parse_app_version(
            args.old_app_version,
            optional_minor_and_patch=args.optional_minor_and_patch,
        )
        parsed_new_app_version: ParsedAppVersion = parse_app_version(
            new_app_version,
            optional_minor_and_patch=args.optional_minor_and_patch,
        )

        raw_policy: Any = get_policy_value(chart_data)
        policy: dict[AppChange, ChartBump] = resolve_policy(raw_policy)

        decision = decide_chart_version(
            old_app_version=old_app_version,
            new_app_version=parsed_new_app_version,
            old_chart_version=old_chart_version,
            policy=policy,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.in_place and decision.should_bump:
        changed: bool = update_chart_version_in_place(
            args.chart_path,
            decision.new_chart_version,
        )
        if changed:
            decision = Decision(
                should_bump=decision.should_bump,
                app_change=decision.app_change,
                chart_bump=decision.chart_bump,
                old_chart_version=decision.old_chart_version,
                new_chart_version=decision.new_chart_version,
                old_app_version=decision.old_app_version,
                new_app_version=decision.new_app_version,
                reason=f"{decision.reason}; Chart.yaml updated in place",
            )

    if args.json:
        print(json.dumps(decision.__dict__, indent=2, sort_keys=True))
    else:
        print(format_text_output(decision))

    return 0


if __name__ == "__main__":
    sys.exit(main())
