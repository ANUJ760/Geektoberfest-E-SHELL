import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import commands


class FileOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.workspace_dir = self.project_dir / "workspace"
        self.project_dir_patch = patch.object(commands, "PROJECT_DIR", self.project_dir)
        self.workspace_dir_patch = patch.object(commands, "WORKSPACE_DIR", self.workspace_dir)
        self.project_dir_patch.start()
        self.workspace_dir_patch.start()
        commands.APPROVED_RUN_FILES.clear()

    def tearDown(self):
        self.workspace_dir_patch.stop()
        self.project_dir_patch.stop()
        commands.APPROVED_RUN_FILES.clear()
        self.temp_dir.cleanup()

    def capture_output(self, text):
        output = io.StringIO()
        with redirect_stdout(output):
            commands.handle_command(text)
        return output.getvalue()

    def test_touch_creates_file_in_project_directory(self):
        output = self.capture_output("touch notes.txt")

        self.assertTrue((self.project_dir / "notes.txt").is_file())
        self.assertIn("Created file: notes.txt", output)

    def test_mkdir_creates_folder_in_project_directory(self):
        output = self.capture_output("mkdir examples")

        self.assertTrue((self.project_dir / "examples").is_dir())
        self.assertIn("Created folder: examples", output)

    def test_copy_copies_existing_file(self):
        (self.project_dir / "notes.txt").write_text("hello")

        output = self.capture_output("cp notes.txt backup.txt")

        self.assertEqual((self.project_dir / "backup.txt").read_text(), "hello")
        self.assertIn("Copied notes.txt to backup.txt", output)

    def test_friendly_file_aliases_reuse_safe_handlers(self):
        output = self.capture_output("create file notes.txt")
        self.assertTrue((self.project_dir / "notes.txt").is_file())
        self.assertIn("Created file: notes.txt", output)

        output = self.capture_output("create folder examples")
        self.assertTrue((self.project_dir / "examples").is_dir())
        self.assertIn("Created folder: examples", output)

        (self.project_dir / "source.txt").write_text("hello")
        output = self.capture_output("copy source.txt to duplicate.txt")
        self.assertEqual((self.project_dir / "duplicate.txt").read_text(), "hello")
        self.assertIn("Copied source.txt to duplicate.txt", output)

    def test_unsafe_names_are_blocked(self):
        blocked_names = [
            "../escape.txt",
            "folder/file.txt",
            "~notes.txt",
            "*.txt",
            "file?.txt",
            "a&b.txt",
            "a|b.txt",
            "a;b.txt",
            "a$b.txt",
            "a`b.txt",
            "a>b.txt",
            "a<b.txt",
        ]

        for name in blocked_names:
            with self.subTest(name=name):
                output = self.capture_output(f'touch "{name}"')
                self.assertIn("Blocked unsafe name", output)

    def test_missing_arguments_are_requested(self):
        self.assertIn("Please provide a file name", self.capture_output("touch"))
        self.assertIn("Please provide a folder name", self.capture_output("mkdir"))
        self.assertIn("Please provide a source and destination", self.capture_output("cp notes.txt"))
        self.assertIn("Please provide a file name", self.capture_output("create file"))
        self.assertIn("Please provide a folder name", self.capture_output("create folder"))
        self.assertIn("Please use: copy source to destination", self.capture_output("copy notes.txt"))

    def test_copy_requires_existing_source_file(self):
        output = self.capture_output("cp missing.txt backup.txt")

        self.assertIn("Source file does not exist: missing.txt", output)
        self.assertFalse((self.project_dir / "backup.txt").exists())

    def test_workspace_filename_validation_blocks_unsafe_paths(self):
        for name in ("../escape.py", "folder/file.py", "~notes.py", "*.py", "a;b.py"):
            with self.subTest(name=name):
                output = self.capture_output(f'run "{name}"')
                self.assertIn("Blocked unsafe filename", output)

    @patch("commands.subprocess.run")
    def test_edit_file_uses_only_allowed_editors_in_workspace(self, run):
        output = self.capture_output("open notes.py in nano")

        self.assertTrue(self.workspace_dir.is_dir())
        run.assert_called_once_with(["nano", str(self.workspace_dir / "notes.py")], check=False)
        self.assertEqual(output, "")

    @patch("commands.subprocess.run")
    def test_edit_file_blocks_other_editors(self, run):
        output = self.capture_output("open notes.py in word")
        self.assertIn("Unsupported editor", output)


    @patch("commands.subprocess.run")
    def test_make_executable_uses_chmod_plus_x_only_in_workspace(self, run):
        self.workspace_dir.mkdir()
        script = self.workspace_dir / "script.sh"
        script.write_text("echo hello")

        output = self.capture_output("make script.sh executable")

        run.assert_called_once_with(["chmod", "+x", str(script)], check=False)
        self.assertIn("Made executable: script.sh", output)

    def test_unavailable_chmod_shows_friendly_warning(self):
        self.workspace_dir.mkdir()
        script = self.workspace_dir / "script.sh"
        script.write_text("echo hello")
        with patch("commands.subprocess.run", side_effect=FileNotFoundError):
            output = self.capture_output("make script.sh executable")
        self.assertIn("⚠️ Command not available: chmod", output)

    @patch("commands.subprocess.run")
    def test_run_python_file_asks_first_and_captures_output(self, run):
        self.workspace_dir.mkdir()
        script = self.workspace_dir / "hello.py"
        script.write_text("print('hello')")
        run.return_value = commands.subprocess.CompletedProcess(
            ["python3", str(script)], 0, stdout="hello\n", stderr=""
        )

        with patch("builtins.input", return_value="yes"):
            output = self.capture_output("run hello.py")

        run.assert_called_once_with(
            ["python3", str(script)],
            cwd=None,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertIn("hello", output)

    @patch("commands.subprocess.run")
    def test_run_c_file_prints_compiler_errors(self, run):
        self.workspace_dir.mkdir()
        source = self.workspace_dir / "bad.c"
        source.write_text("bad code")
        run.return_value = commands.subprocess.CompletedProcess(
            ["gcc", str(source), "-o", str(source.with_suffix(""))],
            1,
            stdout="",
            stderr="compile failed\n",
        )

        with patch("builtins.input", return_value="yes"):
            output = self.capture_output("run bad.c")

        self.assertIn("compile failed", output)
        self.assertIn("Compiler errors are shown above.", output)
        self.assertEqual(run.call_count, 1)

    @patch("commands.subprocess.run")
    def test_dangerous_commands_are_blocked(self, run):
        for text in (
            "rm file.txt",
            "sudo apt update",
            "chmod 777 file.txt",
            "chmod 755 file.txt",
            "chown me file.txt",
        ):
            with self.subTest(text=text):
                output = self.capture_output(text)
                self.assertIn("Blocked dangerous command.", output)

        run.assert_not_called()


class CommandRoutingTests(unittest.TestCase):
    @patch("commands.run_command")
    @patch("commands.predict_intent", return_value="python_version")
    def test_python_version_uses_safe_argument_list(self, _predict_intent, run_command):
        with redirect_stdout(io.StringIO()):
            commands.handle_command("python version")

        run_command.assert_called_once_with(["python3", "--version"])

    @patch("commands.launch_background")
    @patch("commands.predict_intent", return_value="open_firefox")
    def test_open_firefox_still_uses_intent_routing(self, _predict_intent, launch_background):
        with redirect_stdout(io.StringIO()):
            commands.handle_command("open firefox")

        launch_background.assert_called_once_with(["firefox"])

    @patch("commands.run_command")
    @patch("commands.shutil.which", return_value=None)
    def test_fastfetch_fallback_uses_safe_commands(self, _which, run_command):
        with redirect_stdout(io.StringIO()):
            commands.show_fastfetch_info()

        self.assertEqual(
            [call.args[0] for call in run_command.call_args_list],
            [["uname", "-a"], ["lscpu"], ["free", "-h"], ["df", "-h"]],
        )

    @patch("commands.run_command")
    @patch("commands.launch_background")
    @patch("commands.predict_intent", return_value="unknown")
    def test_unknown_input_suggests_help_and_runs_nothing(
        self, _predict_intent, launch_background, run_command
    ):
        output = io.StringIO()
        with redirect_stdout(output):
            commands.handle_command("blorp the frobnicator")
        output = output.getvalue()

        self.assertIn("did not run anything", output)
        self.assertIn("help", output)
        self.assertIn("rephras", output)
        run_command.assert_not_called()
        launch_background.assert_not_called()

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_ps_shows_friendly_warning(self, _which):
        output = io.StringIO()
        with redirect_stdout(output):
            commands.show_running_processes()
        self.assertIn("⚠️ ps is not installed", output.getvalue())

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_uptime_uses_proc_fallback(self, _which):
        output = io.StringIO()
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", return_value="3660.00 7000.00"
        ), redirect_stdout(output):
            commands.show_system_uptime()
        self.assertIn("System uptime (fallback)", output.getvalue())

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_uptime_fails_gracefully_without_proc(self, _which):
        output = io.StringIO()
        with patch.object(Path, "is_file", return_value=False), redirect_stdout(output):
            commands.show_system_uptime()
        self.assertIn("⚠️ System uptime is unavailable", output.getvalue())

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_df_uses_disk_usage_fallback(self, _which):
        from collections import namedtuple
        Usage = namedtuple("Usage", ["total", "used", "free"])
        output = io.StringIO()
        with patch("commands.shutil.disk_usage", return_value=Usage(100 * 1024**3, 40 * 1024**3, 60 * 1024**3)), redirect_stdout(output):
            commands.show_disk_usage()
        self.assertIn("Root filesystem (fallback)", output.getvalue())

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_free_uses_proc_meminfo_fallback(self, _which):
        output = io.StringIO()
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", return_value="MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n"
        ), redirect_stdout(output):
            commands.show_memory_usage()
        self.assertIn("Memory (fallback from /proc/meminfo)", output.getvalue())

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_kernel_info_uses_platform_fallback(self, _which):
        output = io.StringIO()
        with redirect_stdout(output):
            commands.show_kernel_info()
        self.assertIn("Kernel info (fallback)", output.getvalue())

    @patch("commands.shutil.which", return_value=None)
    def test_unavailable_whoami_uses_fallback(self, _which):
        output = io.StringIO()
        with redirect_stdout(output):
            commands.show_current_user()
        self.assertTrue(len(output.getvalue().strip()) > 0)

    @patch("commands.run_command")
    @patch("commands.predict_intent", return_value="unknown")
    def test_make_without_executable_is_treated_as_unknown(self, _predict_intent, run_command):
        output = io.StringIO()
        with redirect_stdout(output):
            commands.handle_command("make the computer do something")
        output = output.getvalue()

        self.assertIn("did not run anything", output)
        self.assertNotIn("make filename executable", output)
        run_command.assert_not_called()

    @patch("commands.predict_intent", return_value="unknown")
    def test_debug_line_hidden_unless_enabled(self, _predict_intent):
        with patch.dict(commands.os.environ, {}, clear=False):
            commands.os.environ.pop("ESHELL_DEBUG", None)
            output = io.StringIO()
            with redirect_stdout(output):
                commands.handle_command("asdf qwerty")
            self.assertNotIn("[DEBUG]", output.getvalue())

        with patch.dict(commands.os.environ, {"ESHELL_DEBUG": "1"}):
            output = io.StringIO()
            with redirect_stdout(output):
                commands.handle_command("asdf qwerty")
            self.assertIn("[DEBUG] Predicted intent: unknown", output.getvalue())


if __name__ == "__main__":
    unittest.main()
