#!/usr/bin/env python3
"""Compile production code and the complete unmodified pinned SDK; no bundle build."""
import argparse
import pathlib
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--source-root", type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parents[2])
args = parser.parse_args()
root = args.source_root.resolve()
sdk = root / "4D-Plugin-SDK" / "4D Plugin API"
harness = pathlib.Path(__file__).with_name("ownership.cpp").resolve()
flags = shlex.split(subprocess.check_output(
    ["pkg-config", "--cflags", "--libs", "libpodofo"], text=True))
with tempfile.TemporaryDirectory(prefix="facturx-ownership-") as directory:
    exe = pathlib.Path(directory) / "ownership"
    subprocess.run([
        "clang++", "-std=c++17", "-g", "-O1", "-fno-omit-frame-pointer",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-Wno-multichar", "-Wno-int-conversion", "-Wno-null-conversion",
        "-Wno-deprecated-declarations",
        "-I", str(sdk), f'-DFACTURX_SOURCE="{root / "facturx/facturx-4dplugin.cpp"}"',
        str(harness), "-x", "c++", str(sdk / "4DPluginAPI.c"),
        "-framework", "CoreGraphics", "-framework", "CoreFoundation",
        *flags, "-o", str(exe),
    ], check=True)
    failures = []
    for name in ("property", "collection", "property-untouched", "collection-untouched",
                 "default-variable", "success"):
        result = subprocess.run([str(exe), name])
        if result.returncode:
            failures.append(name)
    if failures:
        raise SystemExit("FAILED: " + ", ".join(failures))
