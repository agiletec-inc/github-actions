#!/usr/bin/env python3
"""Validate and exercise the repository-owned feature flag contract."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path(".airis/flags.toml")
TEMPORARY_KINDS = {"release", "experiment"}
VALID_KINDS = TEMPORARY_KINDS | {"ops", "permission", "kill_switch"}
VALID_TYPES = {"boolean", "string", "number", "json"}
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise ValueError(message)


def require_string(flag: dict[str, Any], name: str, key: str) -> str:
    value = flag.get(name)
    if not isinstance(value, str) or not value.strip():
        fail(f"{key}: {name} must be a non-empty string")
    return value


def parse_date(value: str, key: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        fail(f"{key}: expires must use YYYY-MM-DD")
        raise AssertionError("unreachable")


def parse_test_case(value: Any, name: str, key: str) -> tuple[str, dict[str, str]]:
    if not isinstance(value, dict):
        fail(f"{key}: tests.{name} must be a table")
    command = value.get("command")
    if not isinstance(command, str) or not command.strip():
        fail(f"{key}: tests.{name}.command must be a non-empty string")
    environment = value.get("environment", {})
    if not isinstance(environment, dict) or not all(
        isinstance(env_key, str) and isinstance(env_value, str)
        for env_key, env_value in environment.items()
    ):
        fail(f"{key}: tests.{name}.environment must map strings to strings")
    return command, environment


def validate_flag(flag: Any, today: dt.date) -> tuple[str, list[tuple[str, dict[str, str]]]]:
    if not isinstance(flag, dict):
        fail("Each [[flags]] entry must be a table")
    key = require_string(flag, "key", "<unknown>")
    if not KEY_PATTERN.fullmatch(key):
        fail(f"{key}: invalid key")
    kind = require_string(flag, "kind", key)
    if kind not in VALID_KINDS:
        fail(f"{key}: invalid kind {kind}")
    flag_type = require_string(flag, "type", key)
    if flag_type not in VALID_TYPES:
        fail(f"{key}: invalid type {flag_type}")
    require_string(flag, "owner", key)

    if kind not in TEMPORARY_KINDS:
        return key, []

    expires = parse_date(require_string(flag, "expires", key), key)
    if expires < today:
        fail(f"{key}: expired on {expires.isoformat()}")
    require_string(flag, "cleanup_issue", key)
    tests = flag.get("tests")
    if not isinstance(tests, dict):
        fail(f"{key}: temporary flags require [flags.tests.off] and [flags.tests.on]")
    return key, [
        parse_test_case(tests.get("off"), "off", key),
        parse_test_case(tests.get("on"), "on", key),
    ]


def check(root: Path, today: dt.date) -> None:
    manifest = root / MANIFEST_PATH
    if not manifest.exists():
        print(f"Feature flag check skipped: {MANIFEST_PATH} is not present.")
        return
    try:
        data = tomllib.loads(manifest.read_text())
    except tomllib.TOMLDecodeError as error:
        fail(f"{MANIFEST_PATH}: invalid TOML: {error}")
    flags = data.get("flags", [])
    if not isinstance(flags, list):
        fail(f"{MANIFEST_PATH}: flags must be an array of tables")
    seen: set[str] = set()
    test_cases: list[tuple[str, str, dict[str, str]]] = []
    for flag in flags:
        key, cases = validate_flag(flag, today)
        if key in seen:
            fail(f"{key}: duplicate key")
        seen.add(key)
        test_cases.extend((key, command, environment) for command, environment in cases)
    for key, command, environment in test_cases:
        print(f"Running declared feature flag test for {key}")
        result = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", command],
            cwd=root,
            env=os.environ | environment,
            check=False,
        )
        if result.returncode:
            fail(f"{key}: declared off/on test failed ({result.returncode})")
    print(f"Feature flag check passed: {len(flags)} definitions validated.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args()
    try:
        check(args.root.resolve(), args.today)
    except ValueError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
