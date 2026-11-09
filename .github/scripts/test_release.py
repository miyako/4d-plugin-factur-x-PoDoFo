import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import release


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
FIXTURE_VERSION = "2.3.4"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.previous = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        Path("facturx").mkdir()
        release.VERSION.write_text(FIXTURE_VERSION + "\n")
        release.CMAKE.write_text(
            'include("${CMAKE_CURRENT_SOURCE_DIR}/Version.cmake")\n'
            'MACOSX_BUNDLE_BUNDLE_VERSION "${FACTURX_VERSION}"\n'
            'MACOSX_BUNDLE_SHORT_VERSION_STRING "${FACTURX_VERSION}"\n'
        )
        self.plist = {
            "CFBundlePackageType": "BNDL",
            "CFBundleVersion": "${MACOSX_BUNDLE_BUNDLE_VERSION}",
            "CFBundleShortVersionString": "${MACOSX_BUNDLE_SHORT_VERSION_STRING}",
        }
        self.write_plist()
        self.env = patch.dict(os.environ, {
            "GITHUB_SHA": SHA,
            "GITHUB_REPOSITORY": "owner/repo",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.previous)
        self.temp.cleanup()

    def write_plist(self):
        release.PLIST.write_bytes(plistlib.dumps(self.plist))


class VersionTests(Fixture):
    def test_reference_resolution_and_bump_modes(self):
        for mode, expected in (("patch", "2.3.5"), ("minor", "2.4.0"), ("major", "3.0.0")):
            with self.subTest(mode=mode):
                release.VERSION.write_text(FIXTURE_VERSION + "\n")
                cmake = release.CMAKE.read_bytes()
                plist = release.PLIST.read_bytes()
                self.assertEqual(release.bump(mode), expected)
                self.assertEqual(release.read_version(), expected)
                self.assertEqual(release.CMAKE.read_bytes(), cmake)
                self.assertEqual(release.PLIST.read_bytes(), plist)

    def test_literal_metadata_is_coordinated(self):
        release.CMAKE.write_text(release.CMAKE.read_text().replace("${FACTURX_VERSION}", FIXTURE_VERSION))
        self.plist.update({key: FIXTURE_VERSION for key in release.SETTINGS})
        self.write_plist()
        self.assertEqual(release.bump("patch"), "2.3.5")
        self.assertEqual(release.read_version(), "2.3.5")
        self.assertNotIn(FIXTURE_VERSION, release.CMAKE.read_text())
        self.assertNotIn(FIXTURE_VERSION, release.PLIST.read_text())

    def test_invalid_versions_fail_without_metadata_writes(self):
        for value in ("", "1.2", "v1.2.3", "01.2.3", "1.2.03", "1.2.3-beta", "1.2.3\n\n",
                      "1.2.3;exit", " 1.2.3", "1.2.3\njunk", "1.2.3\r", "1.\r2.3", "１.2.3"):
            with self.subTest(value=value):
                release.VERSION.write_text(value)
                before = release.CMAKE.read_bytes(), release.PLIST.read_bytes()
                with self.assertRaises(ValueError):
                    release.bump("patch")
                self.assertEqual(before, (release.CMAKE.read_bytes(), release.PLIST.read_bytes()))

    def test_cmake_drift_invalid_missing_duplicate(self):
        original = release.CMAKE.read_text()
        for text in (
            original.replace('"${FACTURX_VERSION}"', '"2.3.3"', 1),
            original.replace('"${FACTURX_VERSION}"', '"bad"', 1),
            original.replace('"${FACTURX_VERSION}"', '"${UNKNOWN}"', 1),
            "",
            original + 'MACOSX_BUNDLE_BUNDLE_VERSION "2.3.4"\n',
        ):
            release.CMAKE.write_text(text)
            before = release.VERSION.read_bytes(), release.PLIST.read_bytes()
            with self.subTest(text=text), self.assertRaises(ValueError):
                release.bump("minor")
            self.assertEqual(before, (release.VERSION.read_bytes(), release.PLIST.read_bytes()))

    def test_plist_drift_invalid_missing_and_wrong_references(self):
        original = dict(self.plist)
        for key in release.SETTINGS:
            for value in ("2.3.3", "bad", "${UNKNOWN}", 234, None):
                self.plist = dict(original)
                if value is None:
                    del self.plist[key]
                else:
                    self.plist[key] = value
                self.write_plist()
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    release.read_version()

    def test_built_plist_rejects_references_drift_and_wrong_package(self):
        with self.assertRaises(ValueError):
            release.validate_plist(self.plist, FIXTURE_VERSION, allow_variables=False)
        built = {key: FIXTURE_VERSION for key in release.SETTINGS}
        built["CFBundlePackageType"] = "BNDL"
        release.validate_plist(built, FIXTURE_VERSION, allow_variables=False)
        for key, value in (("CFBundleVersion", "2.3.3"), ("CFBundlePackageType", "APPL")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                release.validate_plist({**built, key: value}, FIXTURE_VERSION, allow_variables=False)

    def test_cli_output(self):
        output = Path("output")
        with patch.dict(os.environ, GITHUB_OUTPUT=str(output)), \
                patch.object(sys, "argv", ["release.py", "version"]), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            release.main()
        self.assertEqual(stdout.getvalue(), "2.3.4\n")
        self.assertEqual(output.read_text(), "version=2.3.4\ntag=v2.3.4\n")

    def test_cmake_loader_validates_and_resolves(self):
        shutil.copyfile(ROOT / "facturx/Version.cmake", "facturx/Version.cmake")
        Path("probe.cmake").write_text(
            'include("${CMAKE_CURRENT_LIST_DIR}/facturx/Version.cmake")\n'
            'file(WRITE "${CMAKE_CURRENT_LIST_DIR}/resolved" "${FACTURX_VERSION}")\n'
            'set(MACOSX_BUNDLE_SHORT_VERSION_STRING "${FACTURX_VERSION}")\n'
            'set(MACOSX_BUNDLE_BUNDLE_VERSION "${FACTURX_VERSION}")\n'
            'configure_file(facturx/Info.plist.in built.plist)\n'
        )
        for value in ("2.3.4", "2.3.4\n", "12.34.56\n", "2.3.4\r\n"):
            release.VERSION.write_text(value)
            self.assertEqual(release.read_version(), value.rstrip("\r\n"))
            subprocess.run(["cmake", "-P", "probe.cmake"], check=True, capture_output=True)
            self.assertEqual(Path("resolved").read_text(), value.rstrip("\r\n"))
            release.validate_plist(
                plistlib.loads(Path("built.plist").read_bytes()),
                value.rstrip("\r\n"), allow_variables=False,
            )
        for value in ("", "1.2", "01.2.3", "1.2.03", "1.2.3-beta", "1.2.3\n\n",
                      "1.2.3\r", "1.\r2.3", " 1.2.3"):
            release.VERSION.write_text(value)
            result = subprocess.run(["cmake", "-P", "probe.cmake"], capture_output=True)
            self.assertNotEqual(result.returncode, 0, value)


class AvailabilityTests(Fixture):
    def test_authenticated_paginated_listing_including_drafts(self):
        with patch.object(release.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 2, "", "")) as git, \
                patch.object(release.subprocess, "check_output",
                             return_value=json.dumps([[{"tag_name": "v1.0.0"}], []])) as api:
            release.ensure_available("v2.3.4")
        self.assertEqual(git.call_args.args[0][-1], "refs/tags/v2.3.4")
        self.assertEqual(api.call_args.args[0], [
            "gh", "api", "--paginate", "--slurp", "repos/owner/repo/releases?per_page=100",
        ])
        for entry in ({"tag_name": "v2.3.4"}, {"tag_name": "v2.3.4", "draft": True}):
            with patch.object(release.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 2, "", "")), \
                    patch.object(release.subprocess, "check_output",
                                 return_value=json.dumps([[], [entry]])), \
                    self.assertRaisesRegex(ValueError, "refusing to replace"):
                release.ensure_available("v2.3.4")

    def test_existing_tag_and_remote_errors_block_without_api(self):
        for code in (0, 1, 128):
            with self.subTest(code=code), \
                    patch.object(release.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], code, "", "remote failed")), \
                    patch.object(release.subprocess, "check_output") as api, \
                    self.assertRaises((ValueError, RuntimeError)):
                release.ensure_available("v2.3.4")
            api.assert_not_called()

    def test_api_errors_and_malformed_responses_are_not_absence(self):
        for error in ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 429", "HTTP 500", "offline"):
            with self.subTest(error=error), \
                    patch.object(release.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], 2, "", "")), \
                    patch.object(release.subprocess, "check_output",
                                 side_effect=subprocess.CalledProcessError(1, ["gh"], stderr=error)), \
                    self.assertRaises(subprocess.CalledProcessError):
                release.ensure_available("v2.3.4")
        for response in ("not json", "null", "[]", "{}", "[{}]", "[[{}]]", '[[{"tag_name": 1}]]'):
            with self.subTest(response=response), \
                    patch.object(release.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], 2, "", "")), \
                    patch.object(release.subprocess, "check_output", return_value=response), \
                    self.assertRaises(ValueError):
                release.ensure_available("v2.3.4")


class PublicationTests(Fixture):
    def setUp(self):
        super().setUp()
        self.assets = ["facturx-2.3.4.zip", "facturx-2.3.4.dmg"]
        for asset in self.assets:
            Path(asset).write_bytes(b"fixture")

    def test_immutable_selected_commit(self):
        with patch.object(release.subprocess, "check_output", return_value=SHA + "\n"):
            self.assertEqual(release.check_commit(), SHA)
        with patch.object(release.subprocess, "check_output", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "does not match"):
                release.check_commit()
        for value in ("main", "", "a" * 39, "A" * 40):
            with patch.dict(os.environ, GITHUB_SHA=value), self.assertRaises(ValueError):
                release.check_commit()

    def test_exact_tag_target_and_publication_order(self):
        calls = []

        def output(args, **kwargs):
            calls.append(args)
            if args[0] == "git":
                return f"{SHA}\trefs/tags/v2.3.4\n"
            raise AssertionError(f"Unexpected output command: {args}")

        with patch.object(release, "check_commit", return_value=SHA), \
                patch.object(release, "ensure_available", side_effect=lambda tag: calls.append(["available", tag])), \
                patch.object(release.subprocess, "run", side_effect=lambda args, **kw: calls.append(args)), \
                patch.object(release.subprocess, "check_output", side_effect=output):
            release.publish(FIXTURE_VERSION, self.assets)
        self.assertEqual(calls, [
            ["available", "v2.3.4"],
            ["git", "tag", "v2.3.4", SHA],
            ["git", "-c", "push.followTags=false", "push", "origin", "refs/tags/v2.3.4:refs/tags/v2.3.4"],
            ["git", "ls-remote", "--exit-code", "--tags", "origin", "refs/tags/v2.3.4"],
            ["gh", "api", "--method", "POST", "repos/owner/repo/releases",
             "-f", "tag_name=v2.3.4", "-f", f"target_commitish={SHA}",
             "-f", "name=v2.3.4", "-F", "draft=false", "-F", "prerelease=false"],
            ["gh", "release", "upload", "v2.3.4", "--repo", "owner/repo", *self.assets],
        ])

    def test_no_publication_for_wrong_version_or_assets(self):
        with patch.object(release, "check_commit", return_value=SHA), \
                patch.object(release, "ensure_available") as available, \
                patch.object(release.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                release.publish("2.3.5", self.assets)
            with self.assertRaises(ValueError):
                release.publish(FIXTURE_VERSION, ["wrong.zip", self.assets[1]])
            for content in (None, b""):
                Path(self.assets[0]).unlink(missing_ok=True)
                if content is not None:
                    Path(self.assets[0]).write_bytes(content)
                with self.assertRaises(ValueError):
                    release.publish(FIXTURE_VERSION, self.assets)
        available.assert_not_called()
        run.assert_not_called()

    def test_collision_at_final_check_stops_tagging(self):
        with patch.object(release, "check_commit", return_value=SHA), \
                patch.object(release, "ensure_available", side_effect=ValueError("collision")), \
                patch.object(release.subprocess, "run") as run, self.assertRaises(ValueError):
            release.publish(FIXTURE_VERSION, self.assets)
        run.assert_not_called()

    def test_failures_never_clean_up_or_overwrite(self):
        for failed_call in range(1, 6):
            calls = []

            def execute(args, **kwargs):
                calls.append(args)
                if len(calls) == failed_call:
                    raise subprocess.CalledProcessError(1, args)
                if args[:2] == ["git", "ls-remote"]:
                    return f"{SHA}\trefs/tags/v2.3.4"

            with self.subTest(failed_call=failed_call), \
                    patch.object(release, "check_commit", return_value=SHA), \
                    patch.object(release, "ensure_available"), \
                    patch.object(release.subprocess, "run", side_effect=execute), \
                    patch.object(release.subprocess, "check_output", side_effect=execute), \
                    self.assertRaises(subprocess.CalledProcessError):
                release.publish(FIXTURE_VERSION, self.assets)
            self.assertEqual(len(calls), failed_call)
            self.assertFalse(any("--force" in c or "--clobber" in c or "delete" in c for c in calls))

    def test_wrong_remote_tag_target_blocks_release(self):
        with patch.object(release, "check_commit", return_value=SHA), \
                patch.object(release, "ensure_available"), \
                patch.object(release.subprocess, "run") as run, \
                patch.object(release.subprocess, "check_output", return_value=f"{'b' * 40}\trefs/tags/v2.3.4"), \
                self.assertRaisesRegex(ValueError, "does not point"):
            release.publish(FIXTURE_VERSION, self.assets)
        self.assertEqual(run.call_count, 2)

    def test_nonforced_push_rejects_real_tag_and_branch_races(self):
        subprocess.run(["git", "init", "--bare", "remote.git"], check=True, capture_output=True)
        subprocess.run(["git", "init", "checkout"], check=True, capture_output=True)
        cwd = Path("checkout")

        def git(*args):
            return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)

        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.test")
        git("remote", "add", "origin", str(Path("remote.git").resolve()))
        git("commit", "--allow-empty", "-m", "first")
        first = git("rev-parse", "HEAD").stdout.strip()
        git("tag", "v2.3.4")
        git("push", "origin", "HEAD:refs/heads/selected", "refs/tags/v2.3.4:refs/tags/v2.3.4")
        git("tag", "-d", "v2.3.4")
        git("commit", "--allow-empty", "-m", "second")
        git("push", "origin", "HEAD:refs/heads/selected")
        git("checkout", "--detach", first)
        git("commit", "--allow-empty", "-m", "racing bump")
        git("tag", "-a", "v9.9.9", "-m", "must not follow")
        git("config", "push.followTags", "true")
        with self.assertRaises(subprocess.CalledProcessError):
            git("-c", "push.followTags=false", "push", "origin", "HEAD:refs/heads/selected")
        git("tag", "v2.3.4")
        with self.assertRaises(subprocess.CalledProcessError):
            git("-c", "push.followTags=false", "push", "origin", "refs/tags/v2.3.4:refs/tags/v2.3.4")
        git("-c", "push.followTags=false", "push", "origin", "HEAD:refs/heads/topic")
        self.assertNotIn("v9.9.9", git("ls-remote", "--tags", "origin").stdout)


class RepositoryTests(unittest.TestCase):
    def test_notarization_gate_accepts_only_two_accepted_results(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        line = next(line.strip() for line in workflow.splitlines()
                    if "r.get(\"status\")" in line)
        command = shlex.split(line.removesuffix("\\").strip())
        command[0] = sys.executable
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / name for name in ("zip.json", "dmg.json")]
            for results, success in (
                ([{"status": "Accepted"}, {"status": "Accepted"}], True),
                ([{"status": "Invalid"}, {"status": "Accepted"}], False),
                ([{"status": "Accepted"}, {"status": "In Progress"}], False),
                ([{}, {"status": "Accepted"}], False),
                ([{"status": "Accepted"}, None], False),
            ):
                for path, result in zip(paths, results):
                    path.write_text(json.dumps(result))
                result = subprocess.run(command + list(map(str, paths)), capture_output=True)
                self.assertEqual(result.returncode == 0, success, results)
            paths[1].write_text("not JSON")
            result = subprocess.run(command + list(map(str, paths)), capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_live_metadata_matches_authoritative_version(self):
        previous = Path.cwd()
        try:
            os.chdir(ROOT)
            self.assertEqual(release.read_version(), release.VERSION.read_text().rstrip("\n"))
        finally:
            os.chdir(previous)
        self.assertIn('include("${CMAKE_CURRENT_SOURCE_DIR}/Version.cmake")',
                      (ROOT / release.CMAKE).read_text())

    def test_zero_input_manual_trigger_and_cross_branch_serialization(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertTrue(workflow.startswith("name: Build\n"))
        trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(trigger.strip(), "workflow_dispatch:")
        concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:", 1)[0]
        self.assertIn("group: release-publication", concurrency)
        self.assertNotIn("github.ref", concurrency)
        self.assertIn("cancel-in-progress: false", concurrency)

    def test_all_release_jobs_use_selected_sha_and_preflight(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        for name in ("version", "build-windows", "build-macos"):
            block = workflow.split(f"\n  {name}:\n", 1)[1].split("\n  build-", 1)[0]
            self.assertIn("ref: ${{ github.sha }}", block)
            self.assertIn("release.py preflight", block)
            if "cmake -S" in block:
                self.assertLess(block.index("release.py preflight"), block.index("cmake -S"))
        self.assertEqual(workflow.count("actions/checkout@"), 3)
        self.assertNotIn("inputs.tag", workflow)
        self.assertNotIn("needs.version.outputs.tag }}", workflow)
        self.assertNotIn("refs/heads/main", workflow)

    def test_publication_requires_existing_build_and_signing_gates(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        mac = workflow.split("\n  build-macos:\n", 1)[1]
        self.assertIn("needs: [version, build-windows]", mac)
        self.assertIn("needs: version", workflow.split("\n  build-windows:\n", 1)[1])
        gates = [
            "release.py preflight", "actions/download-artifact@v4",
            "security import", "notarytool store-credentials",
            "brew install --quiet autoconf automake libtool autoconf-archive",
            "-DVCPKG_TARGET_TRIPLET=arm64-osx-4d",
            "-DVCPKG_TARGET_TRIPLET=x64-osx-4d",
            "lipo -create", "grep -q arm64", "grep -q x86_64",
            "cp winbuild/facturx.4DX", "release.py verify-bundle",
            "codesign --verbose --deep --timestamp --force --options=runtime",
            "ditto -c -k --keepParent", "hdiutil create", 'notarytool submit "$ZIP_PATH"',
            'notarytool submit "$DMG_PATH"', 'r.get("status") == "Accepted"',
            'stapler staple "$DMG_PATH"', 'stapler validate "$DMG_PATH"', "release.py publish",
        ]
        positions = [mac.index(gate) for gate in gates]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(mac.count("release.py verify-bundle"), 2)
        self.assertNotIn("continue-on-error", mac)
        self.assertNotIn("always()", mac)
        self.assertNotIn("softprops/action-gh-release", mac)
        for secret in ("APPLE_DEVELOPER_ID_CERTIFICATE", "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD",
                       "KEYCHAIN_PASSWORD", "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID", "NOTARYTOOL_PASSWORD"):
            self.assertIn("${{ secrets." + secret + " }}", mac)
        windows = workflow.split("\n  build-windows:\n", 1)[1].split("\n  build-macos:", 1)[0]
        for expected in ("-DVCPKG_TARGET_TRIPLET=x64-windows-static-4d",
                         "VCPKG_OVERLAY_TRIPLETS", "actions/upload-artifact@v4",
                         "if-no-files-found: error"):
            self.assertIn(expected, windows)

    def test_bump_is_selected_branch_only_and_no_tags(self):
        workflow = (ROOT / ".github/workflows/bump-version.yml").read_text()
        for expected in ("- patch", "- minor", "- major", "group: bump-version-${{ github.ref }}",
                         "cancel-in-progress: false", "ref: ${{ github.sha }}",
                         "github.ref_type == 'branch'", 'if [ "$REF_TYPE" != branch ]',
                         "release.py check-commit", "release.py bump", "SELECTED_REF: ${{ github.ref }}",
                         'git -c push.followTags=false push origin "HEAD:${SELECTED_REF}"'):
            self.assertIn(expected, workflow)
        for forbidden in ("git tag", "refs/tags/", "--tags", "--force", "gh release", "workflow run"):
            self.assertNotIn(forbidden, workflow)

    def test_independent_test_requirements_remain(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        for expected in ("- '**'", "pull_request:", "fail-fast: false", "windows-latest",
                         "macos-latest", "Verify exported symbols", "make-pdfa3.sh",
                         "--startup-method=test_all", "grep -q PASS", "Select-String",
                         "verapdf --flavour 3b", "brew install --quiet podofo",
                         "-DVCPKG_TARGET_TRIPLET=x64-windows-static-4d"):
            self.assertIn(expected, workflow)

    @unittest.skipIf(os.environ.get("RELEASE_TEST_BUMPED_COPY") == "1", "already testing bumped copy")
    def test_suite_passes_after_bump_in_isolated_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            for relative in (
                "VERSION", "facturx/CMakeLists.txt", "facturx/Version.cmake", "facturx/Info.plist.in",
                ".github/scripts/release.py", ".github/scripts/test_release.py",
                ".github/workflows/release.yml", ".github/workflows/bump-version.yml",
                ".github/workflows/test.yml",
            ):
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            before = (target / "VERSION").read_text().strip()
            result = subprocess.run(
                [sys.executable, ".github/scripts/release.py", "bump", "patch"],
                cwd=target, check=True, text=True, capture_output=True,
                env={key: value for key, value in os.environ.items() if key != "GITHUB_OUTPUT"},
            )
            parts = list(map(int, before.split(".")))
            parts[2] += 1
            expected = ".".join(map(str, parts))
            self.assertEqual(result.stdout.strip(), expected)
            self.assertEqual((target / "VERSION").read_text(), expected + "\n")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", ".github/scripts", "-p", "test_*.py"],
                cwd=target, text=True, capture_output=True,
                env={**os.environ, "RELEASE_TEST_BUMPED_COPY": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
