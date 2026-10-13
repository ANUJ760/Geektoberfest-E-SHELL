import io
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import warnings
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import commands

# Keep the real Popen: setUp mocks subprocess, but creating a directory link on
# Windows needs a real process.
REAL_POPEN = subprocess.Popen


# "PK" followed by 0x01 0x02 starts each entry in a zip file's central directory.
CENTRAL_DIRECTORY_SIGNATURE = bytes([0x50, 0x4B, 0x01, 0x02])


def ok(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def make_directory_link(link, target):
    """Link `link` -> `target`. Returns False when the system does not allow it."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass

    if os.name == "nt":
        # Junctions behave like directory symlinks but need no special privileges.
        process = REAL_POPEN(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.communicate()
        return process.returncode == 0

    return False


class WorkspaceTestCase(unittest.TestCase):
    """Runs handle_command in a throwaway project with subprocess fully mocked."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.project_dir = Path(self.temp_dir.name).resolve()
        self.workspace_dir = self.project_dir / "workspace"
        self.workspace_dir.mkdir()
        for name, value in (("PROJECT_DIR", self.project_dir), ("WORKSPACE_DIR", self.workspace_dir)):
            patcher = patch.object(commands, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        run_patcher = patch("commands.subprocess.run", return_value=ok())
        popen_patcher = patch("commands.subprocess.Popen")
        self.run = run_patcher.start()
        self.popen = popen_patcher.start()
        self.addCleanup(run_patcher.stop)
        self.addCleanup(popen_patcher.stop)

        commands.APPROVED_RUN_FILES.clear()
        self.addCleanup(commands.APPROVED_RUN_FILES.clear)

    def say(self, text, answer="yes"):
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", return_value=answer):
            commands.handle_command(text)
        return output.getvalue()

    def make_file(self, name, text="print('hi')"):
        path = self.workspace_dir / name
        path.write_text(text)
        return path

    def assert_no_subprocess(self):
        self.run.assert_not_called()
        self.popen.assert_not_called()

    def started(self):
        return [call.args[0] for call in self.run.call_args_list]


class GoAndRustTests(WorkspaceTestCase):
    def test_go_file_runs_with_go_run(self):
        path = self.make_file("hello.go", "package main")
        self.run.return_value = ok("hello from go\n")

        output = self.say("run hello.go")

        self.assertIn("hello from go", output)
        self.assertEqual(self.started(), [["go", "run", str(path)]])
        self.assertEqual(self.run.call_args.kwargs["timeout"], commands.RUN_TIMEOUT_SECONDS)
        self.assertNotIn("shell", self.run.call_args.kwargs)

    def test_rust_file_is_compiled_then_the_binary_is_run(self):
        path = self.make_file("hello.rs", "fn main() {}")
        binary = str(path.with_suffix(""))
        self.run.side_effect = [ok(), ok("hello from rust\n")]

        output = self.say("run hello.rs")

        self.assertIn("hello from rust", output)
        self.assertEqual(self.started(), [["rustc", str(path), "-o", binary], [binary]])
        self.assertTrue(all(call.kwargs["timeout"] == 10 for call in self.run.call_args_list))

    def test_rust_compile_errors_are_shown_and_the_program_is_not_run(self):
        self.make_file("bad.rs", "not rust")
        self.run.return_value = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="error: expected item\n"
        )

        output = self.say("run bad.rs")

        self.assertIn("error: expected item", output)
        self.assertIn("Compiler errors are shown above.", output)
        self.assertEqual(len(self.started()), 1)
        self.assertEqual(self.started()[0][0], "rustc")

    def test_go_runtime_errors_are_printed(self):
        self.make_file("boom.go")
        self.run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="panic: boom\n")

        output = self.say("run boom.go")

        self.assertIn("Errors:", output)
        self.assertIn("panic: boom", output)

    def test_missing_go_or_rustc_is_reported_after_one_attempt(self):
        for name, tool in (("a.go", "go"), ("a.rs", "rustc")):
            with self.subTest(tool=tool):
                self.run.reset_mock()
                self.run.side_effect = FileNotFoundError
                self.make_file(name)

                output = self.say(f"run {name}")

                self.assertIn(f"Command not available: {tool}", output)
                self.assertEqual(len(self.started()), 1)
                self.assertEqual(self.started()[0][0], tool)

    def test_a_rust_program_that_times_out_is_stopped(self):
        path = self.make_file("spin.rs")
        binary = str(path.with_suffix(""))
        self.run.side_effect = [ok(), subprocess.TimeoutExpired(cmd=binary, timeout=10)]

        output = self.say("run spin.rs")

        self.assertIn("Stopped after 10 seconds", output)
        self.assertEqual(len(self.started()), 2)

    def test_a_go_program_that_times_out_is_stopped(self):
        self.make_file("spin.go")
        self.run.side_effect = subprocess.TimeoutExpired(cmd="go", timeout=10)

        output = self.say("run spin.go")

        self.assertIn("Stopped after 10 seconds", output)
        self.assertEqual(len(self.started()), 1)

    def test_cancelling_go_and_rust_runs_starts_nothing(self):
        for name in ("a.go", "a.rs"):
            with self.subTest(name=name):
                self.make_file(name)

                output = self.say(f"run {name}", answer="no")

                self.assertIn("Run cancelled.", output)
                self.assert_no_subprocess()

    def test_go_and_rust_still_ask_before_the_first_run(self):
        self.make_file("a.go")
        self.make_file("a.rs")

        with patch("builtins.input", return_value="yes") as prompt, redirect_stdout(io.StringIO()):
            commands.handle_command("run a.go")
            commands.handle_command("run a.rs")

        self.assertEqual(prompt.call_count, 2)

    def test_go_and_rust_names_are_validated_like_other_files(self):
        for text in ('run "../x.go"', 'run "a;b.rs"'):
            with self.subTest(text=text):
                self.assertIn("Blocked unsafe filename", self.say(text))

        self.assert_no_subprocess()

    def test_unsupported_message_lists_the_new_types(self):
        self.make_file("notes.txt")

        output = self.say("run notes.txt")

        self.assertIn("Unsupported file type", output)
        self.assertIn(".go", output)
        self.assertIn(".rs", output)
        self.assert_no_subprocess()


def zip_info(name, flag_bits=0, mode=None):
    """Build a ZipInfo whose name is stored exactly as given."""
    info = zipfile.ZipInfo("placeholder")
    info.filename = name
    info.flag_bits = flag_bits
    if mode is not None:
        info.external_attr = mode << 16
    return info


class CheckZipMemberTests(unittest.TestCase):
    def test_plain_names_are_accepted_and_split_into_parts(self):
        for name, parts in (
            ("a.txt", ["a.txt"]),
            ("src/main.go", ["src", "main.go"]),
            ("./a.txt", ["a.txt"]),
            ("a//b.txt", ["a", "b.txt"]),
            ("docs/", ["docs"]),
        ):
            with self.subTest(name=name):
                self.assertEqual(commands.check_zip_member(zip_info(name)), (parts, None))

    def test_unsafe_names_are_rejected_with_a_reason(self):
        backslash = chr(92)
        cases = {
            "../evil.txt": "..",
            "a/../../evil.txt": "..",
            "..": "..",
            "/etc/passwd": "absolute",
            "C:/Windows/evil.txt": "absolute",
            f"..{backslash}evil.txt": "backslash",
            f"a{backslash}b.txt": "backslash",
            "a" + chr(0) + "b": "null",
            "": "empty",
            "./": "empty",
            "a;b.txt": "blocked character",
            "dir/$HOME": "blocked character",
            "dir/a*.txt": "blocked character",
            "~root/a.txt": "blocked character",
        }

        for name, reason in cases.items():
            with self.subTest(name=name):
                parts, message = commands.check_zip_member(zip_info(name))
                self.assertIsNone(parts)
                self.assertIn(reason, message)

    def test_encrypted_entries_are_rejected(self):
        parts, message = commands.check_zip_member(zip_info("a.txt", flag_bits=0x1))

        self.assertIsNone(parts)
        self.assertIn("encrypted", message)

    def test_links_and_special_files_are_rejected(self):
        for kind in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK):
            with self.subTest(kind=kind):
                parts, message = commands.check_zip_member(zip_info("a", mode=kind | 0o777))
                self.assertIsNone(parts)
                self.assertIn("links and special files", message)

    def test_regular_files_and_directories_are_accepted(self):
        for kind in (stat.S_IFREG, stat.S_IFDIR):
            with self.subTest(kind=kind):
                parts, message = commands.check_zip_member(zip_info("a", mode=kind | 0o644))
                self.assertEqual((parts, message), (["a"], None))


class UnzipTests(WorkspaceTestCase):
    def make_zip(self, name="project.zip", entries=None, compression=zipfile.ZIP_DEFLATED):
        """entries: list of (name_or_ZipInfo, bytes)."""
        path = self.workspace_dir / name
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w", compression) as archive:
                for entry, data in entries or []:
                    archive.writestr(entry, data)
        return path

    def workspace_files(self):
        return sorted(
            str(path.relative_to(self.workspace_dir)).replace(os.sep, "/")
            for path in self.workspace_dir.rglob("*")
        )

    def assert_blocked(self, output, *parts):
        self.assertIn("Blocked unsafe archive", output)
        self.assertIn("Nothing was extracted.", output)
        for part in parts:
            self.assertIn(part, output)
        self.assert_no_subprocess()

    # Extraction that should work.

    def test_files_and_folders_are_extracted_into_workspace(self):
        self.make_zip(entries=[("hello.py", b"print('hi')"), ("src/", b""), ("src/main.go", b"package main")])

        output = self.say("unzip project.zip")

        self.assertIn("Extracted 2 file(s) from project.zip into workspace/", output)
        self.assertEqual((self.workspace_dir / "hello.py").read_bytes(), b"print('hi')")
        self.assertEqual((self.workspace_dir / "src" / "main.go").read_bytes(), b"package main")
        self.assertTrue((self.workspace_dir / "src").is_dir())
        self.assert_no_subprocess()

    def test_parent_folders_are_created_when_the_archive_has_no_folder_entries(self):
        self.make_zip(entries=[("a/b/c.txt", b"deep")])

        self.say("unzip project.zip")

        self.assertEqual((self.workspace_dir / "a" / "b" / "c.txt").read_bytes(), b"deep")

    def test_extract_works_as_an_alias_and_zip_suffix_is_case_insensitive(self):
        self.make_zip(name="PROJECT.ZIP", entries=[("a.txt", b"a")])

        output = self.say("extract PROJECT.ZIP")

        self.assertIn("Extracted 1 file(s)", output)
        self.assertTrue((self.workspace_dir / "a.txt").is_file())

    def test_an_existing_folder_can_be_reused_by_a_folder_entry(self):
        (self.workspace_dir / "src").mkdir()
        self.make_zip(entries=[("src/", b""), ("src/a.txt", b"a")])

        output = self.say("unzip project.zip")

        self.assertIn("Extracted 1 file(s)", output)

    def test_extracted_code_is_not_approved_or_run(self):
        self.make_zip(entries=[("hello.py", b"print('hi')")])

        self.say("unzip project.zip")

        self.assertEqual(commands.APPROVED_RUN_FILES, set())
        self.assert_no_subprocess()

        output = self.say("run hello.py", answer="no")

        self.assertIn("Run cancelled.", output)
        self.assert_no_subprocess()

    @unittest.skipIf(os.name == "nt", "execute bits do not apply on Windows")
    def test_extracted_files_never_become_executable(self):
        info = zip_info("run.sh", mode=stat.S_IFREG | 0o777)
        self.make_zip(entries=[(info, b"echo hi")])

        self.say("unzip project.zip")

        mode = (self.workspace_dir / "run.sh").stat().st_mode
        self.assertFalse(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    # Command handling.

    def test_usage_is_explained_when_the_name_is_missing_or_extra(self):
        for text in ("unzip", "unzip a.zip b.zip"):
            with self.subTest(text=text):
                self.assertIn("Please provide one archive name", self.say(text))

        self.assert_no_subprocess()

    def test_unsafe_archive_names_are_blocked_before_anything_is_read(self):
        for text in ('unzip "../project.zip"', 'unzip "sub/project.zip"', 'unzip "a;b.zip"'):
            with self.subTest(text=text):
                self.assertIn("Blocked unsafe filename", self.say(text))

        self.assert_no_subprocess()

    def test_only_zip_files_are_accepted(self):
        for name in ("project.tar", "project.zip.txt", "project"):
            with self.subTest(name=name):
                self.make_file(name)
                self.assertIn("Only .zip archives are supported.", self.say(f"unzip {name}"))

    def test_missing_archive_is_reported(self):
        self.assertIn("File does not exist in workspace: missing.zip", self.say("unzip missing.zip"))

    def test_a_file_that_is_not_a_zip_is_reported_and_nothing_is_written(self):
        self.make_file("fake.zip", "this is not a zip file")
        before = self.workspace_files()

        output = self.say("unzip fake.zip")

        self.assertIn("not a valid zip file", output)
        self.assertIn("Nothing was extracted.", output)
        self.assertEqual(self.workspace_files(), before)

    def test_an_empty_archive_is_reported(self):
        self.make_zip(entries=[])

        self.assert_blocked(self.say("unzip project.zip"), "empty")

    # Unsafe archives: each must be refused whole, writing nothing anywhere.

    def test_path_traversal_entries_block_the_whole_archive(self):
        names = ("../evil.txt", "a/../../evil.txt", "/evil.txt", "C:/evil.txt", chr(92) + "evil.txt")
        for name in names:
            with self.subTest(name=name):
                self.make_zip(entries=[("good.txt", b"good"), (zip_info(name), b"evil")])
                before = self.workspace_files()

                output = self.say("unzip project.zip")

                self.assert_blocked(output, "unsafe entry")
                self.assertEqual(self.workspace_files(), before)
                self.assertFalse((self.project_dir / "evil.txt").exists())
                self.assertFalse((self.workspace_dir / "good.txt").exists())
                (self.workspace_dir / "project.zip").unlink()

    def test_backslash_traversal_is_blocked_on_any_system(self):
        backslash = chr(92)
        self.make_zip(entries=[(zip_info(f"..{backslash}evil.txt"), b"evil")])

        output = self.say("unzip project.zip")

        self.assert_blocked(output)
        self.assertFalse((self.project_dir / "evil.txt").exists())

    def test_symlink_entries_are_blocked(self):
        link = zip_info("link", mode=stat.S_IFLNK | 0o777)
        self.make_zip(entries=[("good.txt", b"good"), (link, b"/etc/passwd")])

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "links and special files")
        self.assertFalse((self.workspace_dir / "link").exists())
        self.assertFalse((self.workspace_dir / "good.txt").exists())

    def test_encrypted_entries_are_blocked(self):
        path = self.make_zip(entries=[("ok.txt", b"ok"), ("secret.txt", b"data")])
        # zipfile cannot write encrypted entries, so set the "encrypted" flag
        # (bit 0 of the general purpose flags) in the central directory by hand.
        data = bytearray(path.read_bytes())
        directory = data.rindex(CENTRAL_DIRECTORY_SIGNATURE)
        data[directory + 8] |= 0x1
        path.write_bytes(bytes(data))

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "encrypted")
        self.assertFalse((self.workspace_dir / "ok.txt").exists())

    def test_names_with_shell_symbols_are_blocked(self):
        self.make_zip(entries=[("ok.txt", b"ok"), ("bad;name.txt", b"x")])

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "blocked character")
        self.assertFalse((self.workspace_dir / "ok.txt").exists())

    def test_existing_files_are_never_overwritten(self):
        keep = self.make_file("hello.py", "keep me")
        self.make_zip(entries=[("new.txt", b"new"), ("hello.py", b"overwritten")])

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "already exists", "hello.py")
        self.assertEqual(keep.read_text(), "keep me")
        self.assertFalse((self.workspace_dir / "new.txt").exists())

    def test_the_archive_itself_cannot_be_overwritten(self):
        path = self.make_zip(entries=[("project.zip", b"replacement")])
        original = path.read_bytes()

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "already exists")
        self.assertEqual(path.read_bytes(), original)

    def test_a_file_cannot_replace_an_existing_folder_or_vice_versa(self):
        (self.workspace_dir / "docs").mkdir()
        self.make_file("notes", "i am a file")
        for name in ("docs", "notes/"):
            with self.subTest(name=name):
                self.make_zip(entries=[(name, b"data" if name == "docs" else b"")])

                output = self.say("unzip project.zip")

                self.assert_blocked(output, "already exists")
                (self.workspace_dir / "project.zip").unlink()

    def test_duplicate_entries_are_blocked(self):
        self.make_zip(entries=[("a.txt", b"first"), ("a.txt", b"second")])

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "more than once")
        self.assertFalse((self.workspace_dir / "a.txt").exists())

    def test_entries_that_differ_only_by_dot_segments_count_as_duplicates(self):
        self.make_zip(entries=[("a.txt", b"first"), ("./a.txt", b"second")])

        self.assert_blocked(self.say("unzip project.zip"), "more than once")

    def test_too_many_entries_are_blocked(self):
        self.make_zip(entries=[(f"f{i}.txt", b"x") for i in range(3)])

        with patch.object(commands, "MAX_ZIP_ENTRIES", 2):
            output = self.say("unzip project.zip")

        self.assert_blocked(output, "3 entries (limit 2)")
        self.assertFalse((self.workspace_dir / "f0.txt").exists())

    def test_oversized_archives_are_blocked(self):
        self.make_zip(entries=[("big.bin", b"x" * 2048)])

        with patch.object(commands, "MAX_ZIP_UNPACKED_BYTES", 1024):
            output = self.say("unzip project.zip")

        self.assert_blocked(output, "limit")
        self.assertFalse((self.workspace_dir / "big.bin").exists())

    def test_a_highly_compressed_archive_is_judged_by_its_unpacked_size(self):
        path = self.make_zip(entries=[("zeros.bin", b"\0" * (1024 * 1024))])
        self.assertLess(path.stat().st_size, 10 * 1024)

        with patch.object(commands, "MAX_ZIP_UNPACKED_BYTES", 512 * 1024):
            output = self.say("unzip project.zip")

        self.assert_blocked(output, "limit")
        self.assertFalse((self.workspace_dir / "zeros.bin").exists())

    def test_unpacking_more_than_the_limit_while_writing_is_stopped_and_undone(self):
        self.make_zip(entries=[("a.txt", b"small"), ("big.bin", b"x" * 100)])
        with zipfile.ZipFile(self.workspace_dir / "project.zip") as archive:
            entries, problem = commands.plan_zip_extraction(archive)
            self.assertIsNone(problem)

            with patch.object(commands, "MAX_ZIP_UNPACKED_BYTES", 50):
                with self.assertRaises(commands.ZipExtractionError):
                    commands.write_zip_entries(archive, entries)

        self.assertFalse((self.workspace_dir / "a.txt").exists())
        self.assertFalse((self.workspace_dir / "big.bin").exists())

    def test_a_file_created_after_the_check_is_not_overwritten_or_deleted(self):
        self.make_zip(entries=[("first.txt", b"1"), ("raced.txt", b"from the archive")])
        with zipfile.ZipFile(self.workspace_dir / "project.zip") as archive:
            entries, problem = commands.plan_zip_extraction(archive)
            self.assertIsNone(problem)

            # Someone creates the file between the safety check and the write.
            raced = self.make_file("raced.txt", "already here")
            with self.assertRaises(commands.ZipExtractionError):
                commands.write_zip_entries(archive, entries)

        self.assertEqual(raced.read_text(), "already here")
        self.assertFalse((self.workspace_dir / "first.txt").exists())

    def test_a_failure_part_way_through_undoes_everything_written_so_far(self):
        self.make_file("blocker", "i am a file, not a folder")
        self.make_zip(entries=[("first.txt", b"1"), ("new/dir/second.txt", b"2"), ("blocker/third.txt", b"3")])

        output = self.say("unzip project.zip")

        self.assertIn("Could not extract project.zip", output)
        self.assertIn("Nothing was extracted.", output)
        self.assertEqual(self.workspace_files(), ["blocker", "project.zip"])
        self.assertEqual((self.workspace_dir / "blocker").read_text(), "i am a file, not a folder")
        self.assert_no_subprocess()

    def test_a_corrupt_entry_is_reported_and_earlier_entries_are_undone(self):
        path = self.make_zip(
            entries=[("first.txt", b"first file"), ("second.txt", b"second file data")],
            compression=zipfile.ZIP_STORED,
        )
        data = path.read_bytes()
        assert b"second file data" in data
        path.write_bytes(data.replace(b"second file data", b"second FILE data"))

        output = self.say("unzip project.zip")

        self.assertIn("Could not extract project.zip", output)
        self.assertIn("Nothing was extracted.", output)
        self.assertFalse((self.workspace_dir / "first.txt").exists())
        self.assertFalse((self.workspace_dir / "second.txt").exists())

    def test_an_entry_resolving_outside_workspace_through_a_link_is_blocked(self):
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside, True)
        link = self.workspace_dir / "linked"
        if not make_directory_link(link, outside):
            self.skipTest("directory links are not available on this system")
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        self.make_zip(entries=[("good.txt", b"good"), ("linked/evil.txt", b"evil")])

        output = self.say("unzip project.zip")

        self.assert_blocked(output, "resolves outside workspace/")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.workspace_dir / "good.txt").exists())

    def test_resolution_outside_workspace_is_blocked_without_needing_real_links(self):
        self.make_zip(entries=[("sneaky.txt", b"evil")])
        outside = self.project_dir / "outside"
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path.name == "sneaky.txt":
                return outside / "sneaky.txt"
            return real_resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve):
            output = self.say("unzip project.zip")

        self.assert_blocked(output, "resolves outside workspace/")
        self.assertFalse(outside.exists())

    def test_the_archive_must_live_inside_workspace(self):
        (self.project_dir / "elsewhere.zip").write_bytes(b"")
        with patch.object(commands, "get_safe_path", wraps=commands.get_safe_path) as safe_path:
            self.say("unzip elsewhere.zip")

        safe_path.assert_called_once_with("elsewhere.zip")
        self.assertIn("File does not exist in workspace", self.say("unzip elsewhere.zip"))
        self.assert_no_subprocess()


class HelpTests(WorkspaceTestCase):
    def test_help_mentions_unzip_and_the_rule_that_protects_it(self):
        output = self.say("help")

        self.assertIn("unzip project.zip", output)
        self.assertIn("refuses unsafe archives", output)


if __name__ == "__main__":
    unittest.main()
