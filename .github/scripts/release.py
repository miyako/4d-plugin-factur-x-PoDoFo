"""Coordinated version metadata and fail-closed release publication."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys


VERSION = Path("VERSION")
CMAKE = Path("facturx/CMakeLists.txt")
PLIST = Path("facturx/Info.plist.in")
SEMVER = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
SETTINGS = {
    "CFBundleShortVersionString": "MACOSX_BUNDLE_SHORT_VERSION_STRING",
    "CFBundleVersion": "MACOSX_BUNDLE_BUNDLE_VERSION",
}


def require_version(value):
    if not isinstance(value, str) or not re.fullmatch(SEMVER, value, re.ASCII):
        raise ValueError(f"Invalid semantic version: {value!r}; expected X.Y.Z without leading zeros")
    return value


def validate_plist(data, version, allow_variables=True):
    for key, setting in SETTINGS.items():
        value = data.get(key)
        if allow_variables and value == f"${{{setting}}}":
            continue
        if require_version(value) != version:
            raise ValueError(f"{key} drift: {value!r} != {version}")
    if data.get("CFBundlePackageType") != "BNDL":
        raise ValueError("The plugin must have CFBundlePackageType BNDL")


def read_version():
    raw = VERSION.read_bytes().decode("utf-8")
    if not re.fullmatch(SEMVER + r"(?:\r?\n)?", raw, re.ASCII):
        raise ValueError("VERSION must contain only X.Y.Z and an optional final newline")
    version = require_version(raw.rstrip("\r\n"))
    cmake = CMAKE.read_text()
    for setting in SETTINGS.values():
        values = re.findall(rf'^\s*{setting}\s+"([^"]+)"', cmake, re.M)
        if len(values) != 1:
            raise ValueError(f"Expected exactly one quoted {setting} in CMake")
        if values[0] != "${FACTURX_VERSION}" and require_version(values[0]) != version:
            raise ValueError(f"{setting} drift: {values[0]!r} != {version}")
    with PLIST.open("rb") as source:
        validate_plist(plistlib.load(source), version)
    return version


def bump(mode):
    current = read_version()
    parts = list(map(int, current.split(".")))
    index = ("major", "minor", "patch").index(mode)
    parts[index] += 1
    parts[index + 1:] = [0] * (2 - index)
    new = ".".join(map(str, parts))
    cmake = CMAKE.read_text()
    for setting in SETTINGS.values():
        cmake = re.sub(
            rf'(^\s*{setting}\s+"){re.escape(current)}(")',
            rf"\g<1>{new}\2", cmake, flags=re.M,
        )
    plist = PLIST.read_text()
    for key in SETTINGS:
        plist = re.sub(
            rf"(<key>{key}</key>\s*<string>){re.escape(current)}(</string>)",
            rf"\g<1>{new}\2", plist,
        )
    CMAKE.write_text(cmake)
    PLIST.write_text(plist)
    VERSION.write_text(new + "\n")
    if read_version() != new:
        raise ValueError("Bumped metadata did not validate")
    return new


def check_commit():
    sha = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"Invalid selected commit: {sha!r}")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != sha:
        raise ValueError(f"Checkout {actual} does not match selected commit {sha}")
    return sha


def ensure_available(tag):
    require_version(tag.removeprefix("v"))
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"],
        text=True, capture_output=True, check=False,
    )
    if result.returncode == 0:
        raise ValueError(f"Tag {tag} already exists; bump the version before building")
    if result.returncode != 2:
        raise RuntimeError(f"Cannot check remote tags: {result.stderr}")
    # Listing with authentication includes drafts and fails on API errors,
    # unlike interpreting an ambiguous release-by-tag 404 as absence.
    pages = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp",
        f"repos/{os.environ['GITHUB_REPOSITORY']}/releases?per_page=100",
    ], text=True))
    if not isinstance(pages, list) or not pages:
        raise ValueError("Invalid release-list response")
    for page in pages:
        if not isinstance(page, list):
            raise ValueError("Invalid release-list page")
        for release in page:
            if not isinstance(release, dict) or not isinstance(release.get("tag_name"), str):
                raise ValueError("Invalid release-list entry")
            if release["tag_name"] == tag:
                raise ValueError(f"Release {tag} already exists; refusing to replace it or its assets")


def publish(version, assets):
    sha = check_commit()
    if read_version() != require_version(version):
        raise ValueError("Publication version differs from selected commit metadata")
    expected = [f"facturx-{version}.zip", f"facturx-{version}.dmg"]
    if [Path(asset).name for asset in assets] != expected:
        raise ValueError(f"Expected release assets {expected}")
    for asset in assets:
        if not Path(asset).is_file() or Path(asset).stat().st_size == 0:
            raise ValueError(f"Missing or empty release asset: {asset}")
    tag = f"v{version}"
    ensure_available(tag)
    subprocess.run(["git", "tag", tag, sha], check=True)
    subprocess.run([
        "git", "-c", "push.followTags=false", "push", "origin",
        f"refs/tags/{tag}:refs/tags/{tag}",
    ], check=True)
    remote = subprocess.check_output(
        ["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"], text=True,
    ).split()
    if remote != [sha, f"refs/tags/{tag}"]:
        raise ValueError("Published tag does not point to the selected commit")
    repository = os.environ["GITHUB_REPOSITORY"]
    # gh release create with assets deletes its draft on upload failure.
    # Create once and upload without clobbering, without any cleanup.
    subprocess.run([
        "gh", "api", "--method", "POST", f"repos/{repository}/releases",
        "-f", f"tag_name={tag}", "-f", f"target_commitish={sha}",
        "-f", f"name={tag}", "-F", "draft=false", "-F", "prerelease=false",
    ], check=True)
    subprocess.run([
        "gh", "release", "upload", tag, "--repo", repository, *assets,
    ], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version")
    commands.add_parser("preflight")
    commands.add_parser("check-commit")
    bump_parser = commands.add_parser("bump")
    bump_parser.add_argument("mode", choices=("patch", "minor", "major"))
    verify = commands.add_parser("verify-bundle")
    verify.add_argument("plist", type=Path)
    release = commands.add_parser("publish")
    release.add_argument("version")
    release.add_argument("assets", nargs=2)
    args = parser.parse_args()
    if args.command == "check-commit":
        check_commit()
        return
    if args.command == "bump":
        version = bump(args.mode)
    elif args.command == "publish":
        publish(args.version, args.assets)
        return
    else:
        version = read_version()
        if args.command == "preflight":
            check_commit()
            ensure_available(f"v{version}")
        elif args.command == "verify-bundle":
            with args.plist.open("rb") as source:
                validate_plist(plistlib.load(source), version, allow_variables=False)
    print(version)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as destination:
            destination.write(f"version={version}\ntag=v{version}\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
