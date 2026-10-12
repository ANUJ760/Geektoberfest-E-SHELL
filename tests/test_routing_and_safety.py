import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import commands
from model import predict_intent


class CommandTestCase(unittest.TestCase):
    """Runs handle_command against a throwaway project directory."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name).resolve()
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


class IntentRoutingTests(CommandTestCase):
    @patch("commands.predict_intent")
    def test_each_intent_calls_its_handler(self, predict):
        handlers = {
            "disk_usage": "show_disk_usage",
            "memory_usage": "show_memory_usage",
            "system_uptime": "show_system_uptime",
            "kernel_info": "show_kernel_info",
            "cpu_info": "show_cpu_info",
            "current_user": "show_current_user",
            "hostname": "show_hostname",
            "os_info": "show_os_info",
            "gpu_info": "show_gpu_info",
            "battery_info": "show_battery_info",
            "network_info": "show_network_info",
            "ip_address": "show_network_info",
            "logged_in_users": "show_logged_in_users",
            "running_processes": "show_running_processes",
            "environment_info": "show_environment_info",
            "python_version": "show_python_version",
            "package_manager_info": "show_package_manager_info",
            "fastfetch_info": "show_fastfetch_info",
        }

        for intent, handler_name in handlers.items():
            with self.subTest(intent=intent):
                predict.return_value = intent
                with patch.object(commands, handler_name) as handler:
                    self.capture_output("some phrase")
                handler.assert_called_once_with()

    @patch("commands.launch_background")
    @patch("commands.run_command")
    @patch("commands.predict_intent")
    def test_simple_intents_use_fixed_argument_lists(self, predict, run_command, launch):
        expected_run = {"list_files": ["ls"], "current_dir": ["pwd"]}
        for intent, args in expected_run.items():
            with self.subTest(intent=intent):
                run_command.reset_mock()
                predict.return_value = intent
                self.capture_output("some phrase")
                run_command.assert_called_once_with(args)

        expected_launch = {"open_firefox": ["firefox"], "calculator": ["gnome-calculator"]}
        for intent, args in expected_launch.items():
            with self.subTest(intent=intent):
                launch.reset_mock()
                predict.return_value = intent
                self.capture_output("some phrase")
                launch.assert_called_once_with(args)

    @patch("commands.predict_intent", return_value="date_time")
    def test_date_time_intent_prints_the_current_time(self, _predict):
        output = self.capture_output("what time is it")

        self.assertRegex(output, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

    @patch("commands.run_command")
    @patch("commands.launch_background")
    @patch("commands.predict_intent")
    def test_file_action_intents_are_not_run_from_the_model(self, predict, launch, run_command):
        # edit_file, make_executable and run_file are only valid through the
        # explicit, validated phrases, never because the classifier guessed them.
        for intent in ("edit_file", "make_executable", "run_file", "not_a_real_intent"):
            with self.subTest(intent=intent):
                predict.return_value = intent
                output = self.capture_output("please do that for me")
                self.assertIn("did not run anything", output)

        run_command.assert_not_called()
        launch.assert_not_called()

    @patch("commands.predict_intent", return_value="unknown")
    def test_unknown_intent_is_reported_not_executed(self, _predict):
        with patch("commands.subprocess.run") as run, patch("commands.subprocess.Popen") as popen:
            output = self.capture_output("blorp the frobnicator")

        self.assertIn("did not run anything", output)
        run.assert_not_called()
        popen.assert_not_called()

    @patch("commands.predict_intent")
    def test_explicit_commands_bypass_the_classifier(self, predict):
        self.workspace_dir.mkdir()
        (self.workspace_dir / "script.sh").write_text("echo hi")
        for text in (
            "help",
            "touch notes.txt",
            "mkdir examples",
            "cp missing.txt other.txt",
            "create file other.txt",
            "create folder other",
            "copy missing.txt to other.txt",
            "make script.sh executable",
            "run missing.py",
            "rm notes.txt",
        ):
            with self.subTest(text=text), patch("commands.subprocess.run"):
                self.capture_output(text)

        predict.assert_not_called()

    @patch("commands.predict_intent")
    def test_blank_input_does_nothing(self, predict):
        for text in ("", "   ", "\t"):
            with self.subTest(text=text):
                self.assertEqual(self.capture_output(text), "")

        predict.assert_not_called()

    @patch("commands.predict_intent")
    def test_unbalanced_quotes_are_reported_without_crashing(self, predict):
        output = self.capture_output('touch "notes.txt')

        self.assertIn("could not read that input", output)
        self.assertFalse((self.project_dir / "notes.txt").exists())
        predict.assert_not_called()

    def test_help_lists_examples_and_safety_rules(self):
        output = self.capture_output("help")

        self.assertIn("disk usage", output)
        self.assertIn("run hello.py", output)
        self.assertIn("File safety rules", output)
        self.assertIn("Destructive commands are intentionally not supported", output)

    def test_gibberish_is_unknown_with_the_real_model(self):
        for text in ("asdf qwerty", "zzzz", "what is the meaning of life"):
            with self.subTest(text=text):
                self.assertEqual(predict_intent(text), "unknown")

    @patch("commands.subprocess.run")
    @patch("commands.subprocess.Popen")
    def test_gibberish_runs_nothing_end_to_end(self, popen, run):
        output = self.capture_output("asdf qwerty")

        self.assertIn("did not run anything", output)
        run.assert_not_called()
        popen.assert_not_called()


class BlockedCommandTests(CommandTestCase):
    @patch("commands.predict_intent")
    @patch("commands.subprocess.Popen")
    @patch("commands.subprocess.run")
    def test_every_blocked_command_is_stopped_before_anything_runs(self, run, popen, predict):
        for name in sorted(commands.BLOCKED_COMMANDS):
            with self.subTest(command=name):
                output = self.capture_output(f"{name} something")
                self.assertIn("Blocked dangerous command.", output)

        run.assert_not_called()
        popen.assert_not_called()
        predict.assert_not_called()

    def test_blocked_command_list_covers_the_documented_set(self):
        documented = {
            "rm", "rmdir", "mv", "chmod", "chown", "sudo",
            "shutdown", "reboot", "kill", "mkfs", "dd",
        }

        self.assertTrue(documented <= commands.BLOCKED_COMMANDS)

    @patch("commands.subprocess.run")
    def test_blocking_ignores_letter_case_and_extra_spacing(self, run):
        for text in ("RM file.txt", "Sudo ls", "SHUTDOWN now", "  rm   -rf  ", "CHMOD 777 x"):
            with self.subTest(text=text):
                self.assertIn("Blocked dangerous command.", self.capture_output(text))

        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_only_the_workspace_make_executable_phrase_changes_permissions(self, run):
        self.assertIn("Blocked dangerous command.", self.capture_output("chmod +x script.sh"))
        self.assertIn("Blocked dangerous command.", self.capture_output("chmod 777 script.sh"))

        run.assert_not_called()


class FilenameValidationTests(CommandTestCase):
    def test_validate_filename_rejects_every_blocked_character(self):
        for part in commands.BLOCKED_NAME_PARTS:
            with self.subTest(part=part), redirect_stdout(io.StringIO()):
                self.assertFalse(commands.validate_filename(f"a{part}b"))

    def test_validate_filename_rejects_empty_names(self):
        for name in ("", None):
            with self.subTest(name=name), redirect_stdout(io.StringIO()) as output:
                self.assertFalse(commands.validate_filename(name))
                self.assertIn("Please provide a file name", output.getvalue())

    def test_validate_filename_accepts_simple_names(self):
        for name in ("notes.txt", "hello.py", "my_script-1.sh", "README", ".hidden"):
            with self.subTest(name=name):
                self.assertTrue(commands.validate_filename(name))

    def test_parent_directory_and_absolute_paths_are_rejected(self):
        for name in ("..", "../x", "/etc/passwd", "C:/Windows/win.ini", "a/../b"):
            with self.subTest(name=name), redirect_stdout(io.StringIO()):
                self.assertIsNone(commands.safe_name(name, "file"))
                self.assertIsNone(commands.get_safe_path(name))

    def test_safe_name_requires_a_name(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(commands.safe_name("", "folder"))

        self.assertIn("Please provide a folder name", output.getvalue())

    def test_safe_name_stays_inside_the_project_directory(self):
        path = commands.safe_name("notes.txt", "file")

        self.assertEqual(path, self.project_dir / "notes.txt")

    def test_get_safe_path_stays_inside_workspace_and_creates_it(self):
        path = commands.get_safe_path("hello.py")

        self.assertEqual(path, self.workspace_dir / "hello.py")
        self.assertTrue(self.workspace_dir.is_dir())

    def test_symlink_pointing_outside_the_project_is_blocked(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.project_dir / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available on this system")

            with redirect_stdout(io.StringIO()) as output:
                self.assertIsNone(commands.safe_name("escape", "folder"))

            self.assertIn("outside the current project directory", output.getvalue())

    def test_symlink_pointing_outside_the_workspace_is_blocked(self):
        self.workspace_dir.mkdir()
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.py"
            target.write_text("print('secret')")
            link = self.workspace_dir / "link.py"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available on this system")

            with redirect_stdout(io.StringIO()) as output:
                self.assertIsNone(commands.get_safe_path("link.py"))

            self.assertIn("outside the workspace folder", output.getvalue())


class FileActionSafetyTests(CommandTestCase):
    def test_touch_and_mkdir_reject_extra_arguments(self):
        self.assertIn("only one file name", self.capture_output("touch a.txt b.txt"))
        self.assertIn("only one folder name", self.capture_output("mkdir a b"))

        self.assertEqual(list(self.project_dir.iterdir()), [])

    def test_touch_keeps_existing_file_content(self):
        (self.project_dir / "notes.txt").write_text("keep me")

        self.capture_output("touch notes.txt")

        self.assertEqual((self.project_dir / "notes.txt").read_text(), "keep me")

    def test_mkdir_reports_existing_folder(self):
        (self.project_dir / "examples").mkdir()

        output = self.capture_output("mkdir examples")

        self.assertIn("Folder already exists: examples", output)

    def test_copy_rejects_extra_arguments(self):
        (self.project_dir / "a.txt").write_text("a")

        output = self.capture_output("cp a.txt b.txt c.txt")

        self.assertIn("only a source and destination", output)
        self.assertFalse((self.project_dir / "b.txt").exists())

    def test_copy_blocks_unsafe_destination_and_source(self):
        (self.project_dir / "a.txt").write_text("a")

        for text in ('cp a.txt "../b.txt"', 'cp a.txt "sub/b.txt"', 'cp "../a.txt" b.txt'):
            with self.subTest(text=text):
                self.assertIn("Blocked unsafe name", self.capture_output(text))

        self.assertEqual([p.name for p in self.project_dir.iterdir()], ["a.txt"])

    def test_copy_alias_requires_the_to_keyword(self):
        (self.project_dir / "a.txt").write_text("a")

        output = self.capture_output("copy a.txt into b.txt")

        self.assertIn("Please use: copy source to destination", output)
        self.assertFalse((self.project_dir / "b.txt").exists())

    @patch("commands.subprocess.run")
    def test_edit_usage_is_explained_for_malformed_phrases(self, run):
        for text in ("edit", "edit a.py b.py"):
            with self.subTest(text=text):
                self.assertIn("Please use: edit filename", self.capture_output(text))

        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_edit_blocks_unsafe_names_before_launching_an_editor(self, run):
        output = self.capture_output('edit "../outside.py"')

        self.assertIn("Blocked unsafe filename", output)
        run.assert_not_called()

    @patch("commands.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_editor_shows_a_friendly_warning(self, _run):
        output = self.capture_output("edit notes.py")

        self.assertIn("Editor not available: nano", output)

    @patch("commands.subprocess.run")
    def test_make_executable_requires_an_existing_workspace_file(self, run):
        output = self.capture_output("make missing.sh executable")

        self.assertIn("File does not exist in workspace: missing.sh", output)
        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_make_executable_blocks_unsafe_names(self, run):
        output = self.capture_output('make "../x.sh" executable')

        self.assertIn("Blocked unsafe filename", output)
        run.assert_not_called()


class RunFileSafetyTests(CommandTestCase):
    def make_file(self, name, text="print('hi')"):
        self.workspace_dir.mkdir(exist_ok=True)
        path = self.workspace_dir / name
        path.write_text(text)
        return path

    @patch("commands.subprocess.run")
    def test_run_is_cancelled_unless_the_user_types_yes(self, run):
        self.make_file("hello.py")

        for answer in ("", "no", "y", "YES please", "yess"):
            with self.subTest(answer=answer), patch("builtins.input", return_value=answer):
                self.assertIn("Run cancelled.", self.capture_output("run hello.py"))

        run.assert_not_called()
        self.assertEqual(commands.APPROVED_RUN_FILES, set())

    @patch("commands.subprocess.run")
    def test_run_accepts_yes_in_any_case_and_remembers_the_approval(self, run):
        path = self.make_file("hello.py")
        run.return_value = commands.subprocess.CompletedProcess([], 0, stdout="hi\n", stderr="")

        with patch("builtins.input", return_value=" YES ") as prompt:
            self.capture_output("run hello.py")
            self.capture_output("run hello.py")

        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(run.call_count, 2)
        self.assertIn(path, commands.APPROVED_RUN_FILES)

    @patch("commands.subprocess.run")
    def test_approval_for_one_file_does_not_cover_another(self, run):
        self.make_file("a.py")
        self.make_file("b.py")
        run.return_value = commands.subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with patch("builtins.input", return_value="yes") as prompt:
            self.capture_output("run a.py")
            self.capture_output("run b.py")

        self.assertEqual(prompt.call_count, 2)

    @patch("commands.subprocess.run")
    def test_run_needs_exactly_one_file_name(self, run):
        for text in ("run", "run a.py b.py"):
            with self.subTest(text=text):
                self.assertIn("Please provide one file name", self.capture_output(text))

        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_run_reports_missing_files_without_prompting(self, run):
        with patch("builtins.input") as prompt:
            output = self.capture_output("run missing.py")

        self.assertIn("File does not exist in workspace: missing.py", output)
        prompt.assert_not_called()
        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_run_blocks_unsafe_names_without_prompting(self, run):
        with patch("builtins.input") as prompt:
            output = self.capture_output('run "../hello.py"')

        self.assertIn("Blocked unsafe filename", output)
        prompt.assert_not_called()
        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_unsupported_file_types_are_not_run(self, run):
        for name in ("notes.txt", "data.json", "program", "tool.exe", "page.html"):
            with self.subTest(name=name):
                self.make_file(name)
                with patch("builtins.input", return_value="yes"):
                    output = self.capture_output(f"run {name}")
                self.assertIn("Unsupported file type", output)

        run.assert_not_called()

    @patch("commands.subprocess.run")
    def test_each_supported_type_uses_its_documented_command(self, run):
        run.return_value = commands.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        ws = self.workspace_dir

        def command_lists(name):
            source = str(ws / name)
            binary = str((ws / name).with_suffix(""))
            return {
                "a.py": [["python3", source]],
                "a.js": [["node", source]],
                "a.sh": [["bash", source]],
                "a.c": [["gcc", source, "-o", binary], [binary]],
                "a.cpp": [["g++", source, "-o", binary], [binary]],
                "a.java": [["javac", source], ["java", "-cp", str(ws), "a"]],
            }[name]

        for name in ("a.py", "a.js", "a.sh", "a.c", "a.cpp", "a.java"):
            with self.subTest(name=name):
                run.reset_mock()
                self.make_file(name)
                with patch("builtins.input", return_value="yes"):
                    self.capture_output(f"run {name}")

                actual = [call.args[0] for call in run.call_args_list]
                self.assertEqual(actual, command_lists(name))

    @patch("commands.subprocess.run")
    def test_run_never_uses_a_shell_and_always_has_a_timeout(self, run):
        self.make_file("hello.py")
        run.return_value = commands.subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with patch("builtins.input", return_value="yes"):
            self.capture_output("run hello.py")

        kwargs = run.call_args.kwargs
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], commands.RUN_TIMEOUT_SECONDS)
        self.assertIsInstance(run.call_args.args[0], list)

    @patch(
        "commands.subprocess.run",
        side_effect=commands.subprocess.TimeoutExpired(cmd="python3", timeout=10),
    )
    def test_long_running_programs_are_stopped_with_a_message(self, _run):
        self.make_file("loop.py", "while True: pass")

        with patch("builtins.input", return_value="yes"):
            output = self.capture_output("run loop.py")

        self.assertIn("Stopped after 10 seconds", output)

    @patch("commands.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_interpreter_shows_a_friendly_warning(self, _run):
        self.make_file("hello.py")

        with patch("builtins.input", return_value="yes"):
            output = self.capture_output("run hello.py")

        self.assertIn("Command not available: python3", output)

    @patch("commands.subprocess.run")
    def test_program_errors_are_printed(self, run):
        self.make_file("boom.py", "raise SystemExit(1)")
        run.return_value = commands.subprocess.CompletedProcess(
            [], 1, stdout="partial\n", stderr="Traceback: boom\n"
        )

        with patch("builtins.input", return_value="yes"):
            output = self.capture_output("run boom.py")

        self.assertIn("partial", output)
        self.assertIn("Errors:", output)
        self.assertIn("Traceback: boom", output)


if __name__ == "__main__":
    unittest.main()
