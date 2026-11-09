"""Helpers for PAN-OS version strings.

A release is "<major>.<minor>.<maintenance>", as 11.2.13, and its hotfixes add
"-h<n>", as 11.2.13-h3. A hotfix only follows its own maintenance release: a
fix in 11.2.13-h3 is in 11.2.13-h4, not in 11.2.12-h9.
"""
import re
from typing import Tuple

VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-h(\d+))?$")
PRODUCT = "PAN-OS"


def version_key(version: str) -> Tuple[int, ...]:
    match = VERSION.match(version)
    if not match:
        raise ValueError(f"not a PAN-OS release: {version!r}")
    major, minor, maintenance, hotfix = match.groups()
    return int(major), int(minor), int(maintenance), int(hotfix or 0)


def is_version(version: str) -> bool:
    return bool(VERSION.match(version))


def branch_of(version: str) -> str:
    return ".".join(version.split(".")[:2])


def train_of(version: str) -> str:
    """The maintenance release a hotfix belongs to: 11.2.13 for 11.2.13-h3."""
    return version.split("-")[0]


def branch_key(branch: str) -> Tuple[int, int]:
    major, minor = branch.split(".")
    return int(major), int(minor)


def bug_key(bug_id: str) -> Tuple[str, int]:
    """PAN-338608 sorts by its number; the prefix (PAN, WF500…) only breaks ties."""
    prefix, _, number = bug_id.rpartition("-")
    return prefix, int(number)
