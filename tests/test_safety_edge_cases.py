import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import commands

# commands.subprocess is the real subprocess module, so patching run() and Popen
# also patches them for these tests.  Keep the real Popen for creating directory links.
REAL_POPEN = subprocess.Popen


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


class SafetyTestCase(unittest.TestCase):
    """Runs handle_command in a throwaway project with subprocess fully mocked.

    Every test checks the user-facing response and whether a subprocess was
    started, using the assertions below.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name).resolve()
        self.workspace_dir = self.project_dir / "workspace"
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
        self.addCleanup(self.temp_dir.cleanup)

    def say(self, text, answer="yes"):
        """Run one command, answering any confirmation prompt with `answer`."""
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", return_value=answer):
            commands.handle_command(text)
        return output.getvalue()

    def call(self, function):
        output = io.StringIO()
        with redirect_stdout(output):
            function()
        return output.getvalue()

    def make_file(self, name, text="print('hi')"):
        self.workspace_dir.mkdir(exist_ok=True)
        path = self.workspace_dir / name
        path.write_text(text)
        return path

    def assert_no_subprocess(self):
        self.run.assert_not_called()
        self.popen.assert_not_called()

    def started(self):
        return [call.args[0] for call in self.run.call_args_list]


class TimedOutProgramTests(SafetyTestCase):
    def timeout(self, command="program"):
        return subprocess.TimeoutExpired(cmd=command, timeout=commands.RUN_TIMEOUT_SECONDS)

    def test_timed_out_script_reports_the_limit_and_was_started_once(self):
        path = self.make_file("loop.py", "while True: pass")
        self.run.side_effect = self.timeout()

        output = self.say("run loop.py")

        self.assertIn("Stopped after 10 seconds because the program took too long.", output)
        self.assertEqual(self.started(), [["python3", str(path)]])
        self.assertEqual(self.run.call_args.kwargs["timeout"], 10)
        self.popen.assert_not_called()

    def test_timeout_message_and_limit_follow_the_configured_value(self):
        self.make_file("loop.py")
        self.run.side_effect = self.timeout()

        with patch.object(commands, "RUN_TIMEOUT_SECONDS", 3):
            output = self.say("run loop.py")

        self.assertIn("Stopped after 3 seconds", output)
        self.assertEqual(self.run.call_args.kwargs["timeout"], 3)

    def test_timed_out_script_prints_no_partial_results_or_errors(self):
        self.make_file("loop.sh", "sleep 100")
        self.run.side_effect = self.timeout()

        output = self.say("run loop.sh")

        self.assertNotIn("Errors:", output)
        self.assertEqual(output.count("Stopped after"), 1)

    def test_timed_out_compile_never_starts_the_program(self):
        for name, compiler in (("a.c", "gcc"), ("a.cpp", "g++"), ("a.java", "javac")):
            with self.subTest(name=name):
                self.run.reset_mock()
                self.run.side_effect = self.timeout(compiler)
                self.make_file(name, "not real code")

                output = self.say(f"run {name}")

                self.assertIn("Stopped after 10 seconds", output)
                self.assertEqual(len(self.started()), 1)
                self.assertEqual(self.started()[0][0], compiler)
                self.assertNotIn("Compiler errors", output)
                self.popen.assert_not_called()

    def test_compiled_program_that_times_out_is_stopped(self):
        path = self.make_file("spin.c", "int main(){for(;;);}")
        binary = str(path.with_suffix(""))
        self.run.side_effect = [ok(), self.timeout(binary)]

        output = self.say("run spin.c")

        self.assertIn("Stopped after 10 seconds", output)
        self.assertEqual(self.started(), [["gcc", str(path), "-o", binary], [binary]])
        self.assertTrue(all(c.kwargs["timeout"] == 10 for c in self.run.call_args_list))

    def test_a_timeout_does_not_block_the_next_command(self):
        self.make_file("loop.py")
        self.run.side_effect = [self.timeout(), ok("fine\n")]

        self.say("run loop.py")
        output = self.say("run loop.py")

        self.assertIn("fine", output)
        self.assertEqual(self.run.call_count, 2)


class UnavailableToolTests(SafetyTestCase):
    def test_missing_interpreter_is_reported_after_a_single_attempt(self):
        for name, tool in (("a.py", "python3"), ("a.js", "node"), ("a.sh", "bash")):
            with self.subTest(tool=tool):
                self.run.reset_mock()
                self.run.side_effect = FileNotFoundError
                path = self.make_file(name)

                output = self.say(f"run {name}")

                self.assertIn(f"Command not available: {tool}", output)
                self.assertEqual(self.started(), [[tool, str(path)]])
                self.popen.assert_not_called()

    def test_missing_compiler_means_the_program_is_never_launched(self):
        for name, compiler in (("a.c", "gcc"), ("a.cpp", "g++"), ("a.java", "javac")):
            with self.subTest(compiler=compiler):
                self.run.reset_mock()
                self.run.side_effect = FileNotFoundError
                self.make_file(name)

                output = self.say(f"run {name}")

                self.assertIn(f"Command not available: {compiler}", output)
                self.assertEqual(len(self.started()), 1)
                self.assertEqual(self.started()[0][0], compiler)
                self.assertNotIn("Compiler errors", output)

    def test_missing_java_runtime_is_reported_after_a_successful_compile(self):
        self.make_file("A.java", "class A {}")
        self.run.side_effect = [ok(), FileNotFoundError]

        output = self.say("run A.java")

        self.assertIn("Command not available: java", output)
        self.assertEqual([args[0] for args in self.started()], ["javac", "java"])

    def test_missing_editor_is_reported_for_each_allowed_editor(self):
        for editor in ("nano", "vim"):
            with self.subTest(editor=editor):
                self.run.reset_mock()
                self.run.side_effect = FileNotFoundError

                output = self.say(f"open notes.py in {editor}")

                self.assertIn(f"Editor not available: {editor}", output)
                self.assertEqual(self.started(), [[editor, str(self.workspace_dir / "notes.py")]])

    def test_missing_chmod_is_reported_and_nothing_else_runs(self):
        self.make_file("script.sh", "echo hi")
        self.run.side_effect = FileNotFoundError

        output = self.say("make script.sh executable")

        self.assertIn("Command not available: chmod", output)
        self.assertNotIn("Made executable", output)
        self.assertEqual(self.started(), [["chmod", "+x", str(self.workspace_dir / "script.sh")]])

    @patch("commands.predict_intent", return_value="open_firefox")
    def test_missing_gui_program_is_reported_without_using_run(self, _predict):
        self.popen.side_effect = FileNotFoundError

        output = self.say("open firefox")

        self.assertIn("Command not available: firefox", output)
        self.popen.assert_called_once_with(["firefox"])
        self.run.assert_not_called()

    @patch("commands.predict_intent", return_value="calculator")
    def test_missing_calculator_is_reported_without_using_run(self, _predict):
        self.popen.side_effect = FileNotFoundError

        output = self.say("open calculator")

        self.assertIn("Command not available: gnome-calculator", output)
        self.popen.assert_called_once_with(["gnome-calculator"])
        self.run.assert_not_called()

    @patch("commands.shutil.which", return_value=None)
    def test_gpu_info_without_lspci_starts_nothing(self, _which):
        output = self.call(commands.show_gpu_info)

        self.assertIn("lspci is not installed", output)
        self.assert_no_subprocess()

    @patch("commands.shutil.which", return_value="/usr/bin/lspci")
    def test_gpu_info_with_lspci_runs_only_lspci(self, _which):
        self.run.return_value = ok("00:02.0 VGA compatible controller: Example GPU\n01:00.0 Ethernet\n")

        output = self.call(commands.show_gpu_info)

        self.assertIn("Example GPU", output)
        self.assertNotIn("Ethernet", output)
        self.assertEqual(self.started(), [["lspci"]])

    @patch("commands.shutil.which", return_value=None)
    def test_running_processes_without_ps_starts_nothing(self, _which):
        output = self.call(commands.show_running_processes)

        self.assertIn("ps is not installed", output)
        self.assert_no_subprocess()

    @patch("commands.shutil.which", return_value="/bin/ps")
    def test_running_processes_reports_ps_vanishing_after_the_check(self, _which):
        self.run.side_effect = FileNotFoundError

        output = self.call(commands.show_running_processes)

        self.assertIn("ps is not installed", output)
        self.assertEqual(self.started(), [["ps", "aux", "--sort=-%mem"]])

    @patch("commands.shutil.which", return_value=None)
    def test_uptime_without_tool_or_proc_starts_nothing(self, _which):
        with patch.object(Path, "is_file", return_value=False):
            output = self.call(commands.show_system_uptime)

        self.assertIn("System uptime is unavailable", output)
        self.assert_no_subprocess()

    @patch("commands.shutil.which", return_value=None)
    def test_python_version_without_python3_reports_the_running_interpreter(self, _which):
        output = self.call(commands.show_python_version)

        self.assertIn("(internal)", output)
        self.assert_no_subprocess()

    @patch("commands.shutil.which", return_value=None)
    def test_network_info_without_ip_or_ifconfig_starts_nothing(self, _which):
        with patch("commands.socket.gethostname", side_effect=OSError):
            output = self.call(commands.show_network_info)

        self.assertIn("Network information is unavailable", output)
        self.assert_no_subprocess()

    @patch("commands.shutil.which", return_value=None)
    def test_logged_in_users_without_who_or_w_starts_nothing(self, _which):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USER", None)
            output = self.call(commands.show_logged_in_users)

        self.assertIn("Logged in users information is unavailable", output)
        self.assert_no_subprocess()

    @patch("commands.shutil.which", return_value=None)
    def test_fastfetch_fallback_survives_every_tool_being_missing(self, _which):
        self.run.side_effect = FileNotFoundError

        output = self.call(commands.show_fastfetch_info)

        self.assertIn("fastfetch is not installed", output)
        for tool in ("uname", "lscpu", "free", "df"):
            self.assertIn(f"Command not available: {tool}", output)
        self.assertEqual(self.started(), [["uname", "-a"], ["lscpu"], ["free", "-h"], ["df", "-h"]])


class CancelledRunTests(SafetyTestCase):
    def test_cancelled_run_starts_nothing_for_every_supported_type(self):
        for name in ("a.py", "a.c", "a.cpp", "a.java", "a.js", "a.sh"):
            with self.subTest(name=name):
                self.make_file(name)

                output = self.say(f"run {name}", answer="no")

                self.assertIn("Run cancelled.", output)
                self.assert_no_subprocess()

        self.assertEqual(commands.APPROVED_RUN_FILES, set())

    def test_cancelled_compiled_run_leaves_no_binary_behind(self):
        self.make_file("hello.c", "int main(){return 0;}")
        before = sorted(p.name for p in self.workspace_dir.iterdir())

        output = self.say("run hello.c", answer="")

        self.assertIn("Run cancelled.", output)
        self.assertEqual(sorted(p.name for p in self.workspace_dir.iterdir()), before)
        self.assert_no_subprocess()

    def test_cancelling_does_not_remember_an_approval(self):
        self.make_file("hello.py")

        self.say("run hello.py", answer="no")
        self.assert_no_subprocess()

        with patch("builtins.input", return_value="yes") as prompt:
            output = io.StringIO()
            with redirect_stdout(output):
                commands.handle_command("run hello.py")

        prompt.assert_called_once()
        self.assertEqual(len(self.started()), 1)

    def test_prompt_names_the_file_before_anything_is_started(self):
        self.make_file("hello.py")

        with patch("builtins.input", return_value="no") as prompt, redirect_stdout(io.StringIO()):
            commands.handle_command("run hello.py")

        self.assertIn("workspace/hello.py", prompt.call_args.args[0])
        self.assert_no_subprocess()

    def test_near_miss_answers_count_as_cancelled(self):
        self.make_file("hello.py")

        for answer in ("y", "Y", "ye", "yes!", "ok", "sure", "true", "1"):
            with self.subTest(answer=answer):
                output = self.say("run hello.py", answer=answer)
                self.assertIn("Run cancelled.", output)
                self.assert_no_subprocess()

    def test_other_commands_never_ask_for_confirmation_or_start_a_program(self):
        for text in ("touch notes.txt", "mkdir examples", "help"):
            with self.subTest(text=text):
                with patch("builtins.input") as prompt, redirect_stdout(io.StringIO()):
                    commands.handle_command(text)
                prompt.assert_not_called()
                self.assert_no_subprocess()


class OutsidePathTests(SafetyTestCase):
    def setUp(self):
        super().setUp()
        self.outside_dir = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: os.path.isdir(self.outside_dir) and self.remove_tree(self.outside_dir))
        (self.outside_dir / "secret.py").write_text("print('secret')")

    @staticmethod
    def remove_tree(path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def link_into(self, parent, name):
        parent.mkdir(exist_ok=True)
        link = parent / name
        if not make_directory_link(link, self.outside_dir):
            self.skipTest("directory links are not available on this system")
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))
        return link

    def fake_resolve_outside(self, name):
        """Make the path called `name` resolve to a file outside its folder."""
        real_resolve = Path.resolve
        escape_target = self.outside_dir / name

        def resolve(path, *args, **kwargs):
            if path.name == name:
                return escape_target
            return real_resolve(path, *args, **kwargs)

        return patch.object(Path, "resolve", resolve)

    # Tests that work everywhere by simulating a path that resolves elsewhere.

    def test_workspace_path_resolving_outside_is_not_run_or_confirmed(self):
        self.make_file("sneaky.py")

        with self.fake_resolve_outside("sneaky.py"), patch("builtins.input") as prompt:
            output = io.StringIO()
            with redirect_stdout(output):
                commands.handle_command("run sneaky.py")

        self.assertIn("Blocked path outside the workspace folder.", output.getvalue())
        prompt.assert_not_called()
        self.assert_no_subprocess()

    def test_workspace_path_resolving_outside_is_not_edited(self):
        with self.fake_resolve_outside("sneaky.py"):
            output = self.say("edit sneaky.py")

        self.assertIn("Blocked path outside the workspace folder.", output)
        self.assert_no_subprocess()

    def test_workspace_path_resolving_outside_does_not_get_chmod(self):
        self.make_file("sneaky.sh")

        with self.fake_resolve_outside("sneaky.sh"):
            output = self.say("make sneaky.sh executable")

        self.assertIn("Blocked path outside the workspace folder.", output)
        self.assertNotIn("Made executable", output)
        self.assert_no_subprocess()

    def test_project_path_resolving_outside_is_not_created(self):
        for text in ("touch sneaky.txt", "mkdir sneaky.txt"):
            with self.subTest(text=text), self.fake_resolve_outside("sneaky.txt"):
                output = self.say(text)
                self.assertIn("Blocked path outside the current project directory.", output)

        self.assertEqual(list(self.outside_dir.iterdir()), [self.outside_dir / "secret.py"])
        self.assertEqual(list(self.project_dir.iterdir()), [])
        self.assert_no_subprocess()

    def test_copy_to_or_from_outside_path_is_blocked(self):
        (self.project_dir / "a.txt").write_text("a")
        (self.project_dir / "sneaky.txt").write_text("x")

        for text in ("cp a.txt sneaky.txt", "cp sneaky.txt b.txt"):
            with self.subTest(text=text), self.fake_resolve_outside("sneaky.txt"):
                output = self.say(text)
                self.assertIn("Blocked path outside the current project directory.", output)

        self.assertEqual(sorted(p.name for p in self.outside_dir.iterdir()), ["secret.py"])
        self.assertFalse((self.project_dir / "b.txt").exists())
        self.assert_no_subprocess()

    # Tests that use a real link to a folder outside the allowed directory.

    def test_workspace_link_to_outside_folder_is_not_run_or_confirmed(self):
        self.link_into(self.workspace_dir, "linked")

        with patch("builtins.input") as prompt, redirect_stdout(io.StringIO()) as output:
            commands.handle_command("run linked")

        self.assertIn("Blocked path outside the workspace folder.", output.getvalue())
        prompt.assert_not_called()
        self.assert_no_subprocess()

    def test_workspace_link_to_outside_folder_is_not_edited_or_chmodded(self):
        self.link_into(self.workspace_dir, "linked")

        for text in ("edit linked", "open linked in vim", "make linked executable"):
            with self.subTest(text=text):
                output = self.say(text)
                self.assertIn("Blocked path outside the workspace folder.", output)

        self.assert_no_subprocess()

    def test_project_link_to_outside_folder_is_not_written_through(self):
        self.link_into(self.project_dir, "linked")
        (self.project_dir / "a.txt").write_text("a")

        for text in ("touch linked", "mkdir linked", "cp a.txt linked", "cp linked b.txt"):
            with self.subTest(text=text):
                output = self.say(text)
                self.assertIn("Blocked path outside the current project directory.", output)

        self.assertEqual(sorted(p.name for p in self.outside_dir.iterdir()), ["secret.py"])
        self.assertFalse((self.project_dir / "b.txt").exists())
        self.assert_no_subprocess()


if __name__ == "__main__":
    unittest.main()
