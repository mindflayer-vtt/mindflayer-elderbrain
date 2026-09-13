#!/usr/bin/env python3
"""Reject secret-bearing artifact paths anywhere in reachable Git history."""
import argparse
from pathlib import PurePosixPath
import re
import subprocess


PROHIBITED = (
    re.compile(r"(^|/)config/private/", re.IGNORECASE),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$", re.IGNORECASE),
    re.compile(r"(^|/).*(private|secret).*[.](key|pem|p12|pfx)$", re.IGNORECASE),
    re.compile(r"[.](p12|pfx|kdbx|borg|tar[.]zst)$", re.IGNORECASE),
    re.compile(r"(^|/)(backup|recovery)[-_]?(archive|kit).*[.](json|zip|tar|zst)$", re.IGNORECASE),
)


def historical_paths(repository):
    command = ["git"]
    if repository.endswith(".git"):
        command.append(f"--git-dir={repository}")
    else:
        command.extend(["-C", repository])
    process = subprocess.run(command + ["log", "--all", "--format=%x00", "--name-only", "-z"],
                             check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return {part.decode("utf-8", "surrogateescape").lstrip("\n")
            for part in process.stdout.split(b"\0") if part.lstrip(b"\n")}


def prohibited(paths):
    findings = []
    for value in paths:
        path = str(PurePosixPath(value))
        if any(pattern.search(path) for pattern in PROHIBITED):
            findings.append(path)
    return sorted(set(findings))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    args = parser.parse_args()
    findings = prohibited(historical_paths(args.repository))
    if findings:
        print("Prohibited secret-bearing artifact paths exist in reachable history:")
        for finding in findings:
            print(f"  {finding}")
        raise SystemExit(1)
