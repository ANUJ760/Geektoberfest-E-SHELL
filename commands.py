import datetime
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from model import predict_intent

# These commands are intentionally read-only or very limited.  Dangerous actions
# such as rm, mv, chmod, chown, sudo, shutdown, reboot, kill, mkfs, and dd are
# blocked by design because a beginner-friendly assistant should not be able to
# delete data, change permissions, or damage the system by accident.
BLOCKED_NAME_PARTS = ("/", "..", "~", "*", "?", "&", "|", ";", "$", "`", ">", "<")
BLOCKED_COMMANDS = {
    "rm",
    "rmdir",
    "mv",
    "sudo",
    "kill",
    "shutdown",
    "reboot",
    "chmod",
    "chown",
    "dd",
    "mkfs",
}
PROJECT_DIR = Path.cwd().resolve()
WORKSPACE_DIR = PROJECT_DIR / "workspace"
ALLOWED_EDITORS = {"nano", "vim"}
RUN_TIMEOUT_SECONDS = 10
APPROVED_RUN_FILES = set()


def run_command(args):
    """Run a known-safe command without invoking a shell."""
    try:
        subprocess.run(args, check=False)
    except FileNotFoundError:
        print(f"⚠️ Command not available: {args[0]}")


def launch_background(args):
    """Start a known GUI program without using a shell."""
    try:
        subprocess.Popen(args)
    except FileNotFoundError:
        print(f"⚠️ Command not available: {args[0]}")


def validate_filename(name):
    """Return True only for simple filenames allowed in the workspace."""
    if not name:
        print("Please provide a file name.")
        return False

    if any(part in name for part in BLOCKED_NAME_PARTS):
        print(
            "Blocked unsafe filename. Use a simple name without /, .., ~, *, ?, &, |, ;, $, `, >, or <."
        )
        return False

    return True


def get_safe_path(filename):
    """Build a safe path inside workspace/ after validating the filename."""
    if not validate_filename(filename):
        return None

    WORKSPACE_DIR.mkdir(exist_ok=True)
    path = (WORKSPACE_DIR / filename).resolve()
    if path.parent != WORKSPACE_DIR.resolve():
        print("Blocked path outside the workspace folder.")
        return None

    return path


def print_completed_process(result):
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print("Errors:")
        print(result.stderr, end="")


def run_and_print(args, cwd=None):
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        print(f"⚠️ Command not available: {args[0]}")
        return None
    except subprocess.TimeoutExpired:
        print(f"Stopped after {RUN_TIMEOUT_SECONDS} seconds because the program took too long.")
        return None

    print_completed_process(result)
    return result


def compile_then_run(compile_args, run_args, cwd=None):
    compile_result = run_and_print(compile_args, cwd=cwd)
    if compile_result is None:
        return
    if compile_result.returncode != 0:
        print("Compiler errors are shown above.")
        return

    run_and_print(run_args, cwd=cwd)


def run_python_file(path):
    run_and_print(["python3", str(path)])


def run_c_file(path):
    output_path = path.with_suffix("")
    compile_then_run(["gcc", str(path), "-o", str(output_path)], [str(output_path)])


def run_cpp_file(path):
    output_path = path.with_suffix("")
    compile_then_run(["g++", str(path), "-o", str(output_path)], [str(output_path)])


def run_java_file(path):
    class_name = path.stem
    compile_then_run(["javac", str(path)], ["java", "-cp", str(WORKSPACE_DIR), class_name])


def run_js_file(path):
    run_and_print(["node", str(path)])


def run_shell_file(path):
    run_and_print(["bash", str(path)])


def print_help():
    print(
        """
Available examples:
  disk usage              cpu info                os info
  gpu info                battery info            network info
  ip address              logged in users         running processes
  environment info        shell info              python version
  package manager info    fastfetch info
  touch notes.txt         mkdir examples          cp notes.txt backup.txt
  create file notes.txt   create folder examples  copy notes.txt to backup.txt
  edit hello.py           open hello.py in nano   open hello.py in vim
  make hello.py executable
  run hello.py

File safety rules:
  - Only simple names in the current project directory are allowed.
  - Paths and shell symbols such as /, .., ~, *, ?, &, |, ;, $, `, >, < are blocked.
  - Editing, chmod +x, and running are limited to files inside workspace/.
  - Destructive commands are intentionally not supported.
""".strip()
    )


def safe_name(name, label):
    """Accept only one simple filename/folder name inside this project folder."""
    if not name:
        print(f"Please provide a {label} name.")
        return None

    if any(part in name for part in BLOCKED_NAME_PARTS):
        print(
            "Blocked unsafe name. Use a simple name without /, .., ~, *, ?, &, |, ;, $, `, >, or <."
        )
        return None

    candidate = (PROJECT_DIR / name).resolve()
    if candidate.parent != PROJECT_DIR:
        print("Blocked path outside the current project directory.")
        return None

    return candidate


def parse_words(text):
    try:
        return shlex.split(text)
    except ValueError:
        print("I could not read that input. Please check the quotes and try again.")
        return []


def handle_edit(words):
    command = words[0].lower()
    if len(words) == 2 and command == "edit":
        editor = "nano"
        filename = words[1]
    elif len(words) == 4 and command == "open" and words[2].lower() == "in":
        filename = words[1]
        editor = words[3].lower()
    else:
        print("Please use: edit filename, open filename in nano, or open filename in vim")
        return

    if editor not in ALLOWED_EDITORS:
        print("Only nano and vim are allowed editors.")
        return

    path = get_safe_path(filename)
    if not path:
        return

    try:
        subprocess.run([editor, str(path)], check=False)
    except FileNotFoundError:
        print(f"⚠️ Editor not available: {editor}")


def handle_make_executable(words):
    if len(words) != 3 or words[0].lower() != "make" or words[2].lower() != "executable":
        print("Please use: make filename executable")
        return

    path = get_safe_path(words[1])
    if not path:
        return
    if not path.is_file():
        print(f"File does not exist in workspace: {path.name}")
        return

    subprocess.run(["chmod", "+x", str(path)], check=False)
    print(f"Made executable: {path.name}")


def ask_before_first_run(path):
    if path in APPROVED_RUN_FILES:
        return True

    answer = input(
        f"Running code can be unsafe. Run workspace/{path.name}? Type yes to continue: "
    )
    if answer.strip().lower() != "yes":
        print("Run cancelled.")
        return False

    APPROVED_RUN_FILES.add(path)
    return True


def handle_run_file(words):
    if len(words) != 2:
        print("Please provide one file name, for example: run hello.py")
        return

    path = get_safe_path(words[1])
    if not path:
        return
    if not path.is_file():
        print(f"File does not exist in workspace: {path.name}")
        return
    if not ask_before_first_run(path):
        return

    runners = {
        ".py": run_python_file,
        ".c": run_c_file,
        ".cpp": run_cpp_file,
        ".java": run_java_file,
        ".js": run_js_file,
        ".sh": run_shell_file,
    }
    runner = runners.get(path.suffix)
    if not runner:
        print("Unsupported file type. Supported: .py, .c, .cpp, .java, .js, .sh")
        return

    runner(path)


def handle_touch(words):
    if len(words) < 2:
        print("Please provide a file name, for example: touch notes.txt")
        return
    if len(words) > 2:
        print("Please provide only one file name, for example: touch notes.txt")
        return

    path = safe_name(words[1], "file")
    if path:
        path.touch(exist_ok=True)
        print(f"Created file: {path.name}")


def handle_mkdir(words):
    if len(words) < 2:
        print("Please provide a folder name, for example: mkdir examples")
        return
    if len(words) > 2:
        print("Please provide only one folder name, for example: mkdir examples")
        return

    path = safe_name(words[1], "folder")
    if not path:
        return

    try:
        path.mkdir(exist_ok=False)
        print(f"Created folder: {path.name}")
    except FileExistsError:
        print(f"Folder already exists: {path.name}")


def handle_copy(words):
    if len(words) < 3:
        print("Please provide a source and destination, for example: cp notes.txt backup.txt")
        return
    if len(words) > 3:
        print("Please provide only a source and destination, for example: cp notes.txt backup.txt")
        return

    source = safe_name(words[1], "source file")
    destination = safe_name(words[2], "destination file")
    if not source or not destination:
        return
    if not source.is_file():
        print(f"Source file does not exist: {source.name}")
        return

    # copy2 preserves useful metadata while still avoiding shell=True entirely.
    shutil.copy2(source, destination)
    print(f"Copied {source.name} to {destination.name}")


def show_gpu_info():
    if not shutil.which("lspci"):
        print("⚠️ lspci is not installed, so GPU information is unavailable.")
        return

    result = subprocess.run(["lspci"], capture_output=True, text=True, check=False)
    gpu_lines = [
        line
        for line in result.stdout.splitlines()
        if any(word in line.lower() for word in ("vga", "3d", "display"))
    ]
    print("\n".join(gpu_lines) if gpu_lines else "No GPU entry found.")


def show_battery_info():
    batteries = sorted(Path("/sys/class/power_supply").glob("BAT*"))
    if not batteries:
        print("No battery information found.")
        return

    for battery in batteries:
        capacity = battery / "capacity"
        status = battery / "status"
        capacity_text = capacity.read_text().strip() if capacity.exists() else "unknown"
        status_text = status.read_text().strip() if status.exists() else "unknown"
        print(f"{battery.name}: {capacity_text}% ({status_text})")


def show_environment_info():
    for key in ("USER", "HOME", "SHELL", "LANG", "TERM", "PATH"):
        print(f"{key}={os.environ.get(key, '')}")


def show_running_processes():
    result = subprocess.run(["ps", "aux", "--sort=-%mem"], capture_output=True, text=True, check=False)
    lines = result.stdout.splitlines()[:11]  # header plus the 10 largest processes
    print("\n".join(lines))


def show_package_manager_info():
    managers = ("apt", "dnf", "pacman", "zypper", "apk")
    found = [manager for manager in managers if shutil.which(manager)]
    print("Detected package manager(s): " + ", ".join(found) if found else "No common package manager detected.")


def show_fastfetch_info():
    if shutil.which("fastfetch"):
        run_command(["fastfetch"])
        return

    print("fastfetch is not installed. Showing safe fallback system information instead.\n")
    for command in (["uname", "-a"], ["lscpu"], ["free", "-h"], ["df", "-h"]):
        print(f"$ {' '.join(command)}")
        run_command(command)
        print()


def print_unknown_feedback(text):
    """Explain that nothing was run and point the user to help or a rephrase."""
    print(f"❓ I didn't understand \"{text}\", so I did not run anything.")
    print("   - Type 'help' to see example commands.")
    print("   - Or try rephrasing, for example: 'disk usage', 'cpu info', or 'who am i'.")


def handle_command(text):
    words = parse_words(text)
    if not words:
        return

    first_word = words[0].lower()
    lowered_words = [word.lower() for word in words]
    if first_word in BLOCKED_COMMANDS or lowered_words[:2] == ["chmod", "777"]:
        print("Blocked dangerous command.")
        return
    if first_word == "help":
        print_help()
        return
    if first_word == "touch":
        handle_touch(words)
        return
    if first_word == "mkdir":
        handle_mkdir(words)
        return
    if first_word == "cp":
        handle_copy(words)
        return
    if first_word == "edit" or (
        first_word == "open" and len(words) == 4 and words[2].lower() == "in"
    ):
        handle_edit(words)
        return
    if first_word == "make":
        handle_make_executable(words)
        return
    if first_word == "run":
        handle_run_file(words)
        return

    # Friendly aliases keep file operations easier to discover while still
    # reusing the same strict validation as the terminal-style forms above.
    if words[:2] == ["create", "file"]:
        handle_touch(["touch", *words[2:]])
        return
    if words[:2] == ["create", "folder"]:
        handle_mkdir(["mkdir", *words[2:]])
        return
    if len(words) >= 1 and words[0] == "copy":
        if len(words) == 4 and words[2] == "to":
            handle_copy(["cp", words[1], words[3]])
        else:
            print("Please use: copy source to destination")
        return

    intent = predict_intent(text)
    print(f"[DEBUG] Predicted intent: {intent}")

    handlers = {
        "list_files": lambda: run_command(["ls"]),
        "current_dir": lambda: run_command(["pwd"]),
        "disk_usage": lambda: run_command(["df", "-h"]),
        "memory_usage": lambda: run_command(["free", "-h"]),
        "date_time": lambda: print(datetime.datetime.now()),
        "system_uptime": lambda: run_command(["uptime"]),
        "kernel_info": lambda: run_command(["uname", "-a"]),
        "cpu_info": lambda: run_command(["lscpu"]),
        "current_user": lambda: run_command(["whoami"]),
        "hostname": lambda: run_command(["hostname"]),
        "open_firefox": lambda: launch_background(["firefox"]),
        "calculator": lambda: launch_background(["gnome-calculator"]),
        "os_info": lambda: run_command(["lsb_release", "-a"]) if shutil.which("lsb_release") else run_command(["cat", "/etc/os-release"]),
        "gpu_info": show_gpu_info,
        "battery_info": show_battery_info,
        "network_info": lambda: run_command(["ip", "addr", "show"]),
        "ip_address": lambda: run_command(["ip", "addr", "show"]),
        "logged_in_users": lambda: run_command(["who"]),
        "running_processes": show_running_processes,
        "environment_info": show_environment_info,
        "shell_info": lambda: print(os.environ.get("SHELL", "Unknown shell")),
        "python_version": lambda: run_command(["python3", "--version"]),
        "package_manager_info": show_package_manager_info,
        "fastfetch_info": show_fastfetch_info,
    }

    handler = handlers.get(intent)
    if handler:
        handler()
    else:
        print_unknown_feedback(text)
