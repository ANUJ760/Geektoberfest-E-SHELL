import datetime
import getpass
import os
import platform
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

from model import predict_intent
from version import __version__, dependency_lines, usage_line
import settings

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
"""
EDITORS now consist all the editors that can be used from REPL.
"EDITOR" : { "EditorName": ["cmd"], "type", ""}
"""
EDITORS = {
    "nano": {"command": ["nano"], "gui": False},
    "vim": {"command": ["vim"], "gui": False},
    "micro": {"command": ["micro"], "gui": False},
    "helix": {"command": ["hx"], "gui": False},
    "emacs": {"command": ["emacs", "-nw"], "gui": False},
    "gedit": {"command": ["gedit"], "gui": True},
}
RUN_TIMEOUT_SECONDS = 10
# ZIP extraction limits keep a single archive from filling the disk.
MAX_ZIP_ENTRIES = 200
MAX_ZIP_UNPACKED_BYTES = 20 * 1024 * 1024
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


def run_go_file(path):
    run_and_print(["go", "run", str(path)])


def run_rust_file(path):
    output_path = path.with_suffix("")
    compile_then_run(["rustc", str(path), "-o", str(output_path)], [str(output_path)])


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
  run hello.py            unzip project.zip       version

File safety rules:
  - Only simple names in the current project directory are allowed.
  - Paths and shell symbols such as /, .., ~, *, ?, &, |, ;, $, `, >, < are blocked.
  - Editing, chmod +x, and running are limited to files inside workspace/.
  - unzip only extracts a .zip from workspace/ into workspace/ and refuses unsafe archives.
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

    if len(words) == 2 and command in {"edit", "open"}: # two values to value through
        filename = words[1]
        editor = choose_default_editor()
    elif len(words) == 4 and command == "open" and words[2].lower() == "in":
        filename = words[1]
        editor = words[3].lower()
    else:   # last fallback for Warning & early return
        print("Use: open filename, edit filename, or open filename in <editor>")
        return
        
    # sanity check for available Editors in EDITORS~
    if editor not in EDITORS:
        supported = ", ".join(EDITORS)
        print(f"Unsupported editor. Supported editors: {supported}.")
        return

    path = get_safe_path(filename)
    if not path:
        return

    editor_config = EDITORS[editor]
    executable = editor_config["command"][0]

    # warn-suggestion if Text editor is available in EDITOR but not on user's system
    if not shutil.which(executable):
        print(
            f"Editor '{editor}' is not installed or is not on PATH. "
            "Install it with your Linux distribution's package manager, "
            "or choose another installed editor."
        )
        return
    # display sanity check
    if editor_config["gui"] and not has_display():
        print(f"'{editor}' needs a graphical display and none was found. Try nano, vim, or micro.")
        return

    # taking args to run subprocess ( true cmd )
    args = [*editor_config["command"], str(path)]

    try:
        # sanity check for GUI vs Terminal base
        if editor_config["gui"]:
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)
            # with new sessiona and cancels warning prompts
        else:
            subprocess.run(args, check=False)
    except OSError as error:
        print(f"Could not open {editor}: {error}")
        return

    record_editor_use(editor)


# the best sanity check
# helpful if somebody is SSH into Linux based machine or using WSLg (wsl2 might give windowsub-pop)
def has_display():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def choose_default_editor():
    # if user has set a global default with envVAR
    override = os.environ.get("E_SHELL_DEFAULT_EDITOR", "").strip().lower()
    if override in EDITORS and shutil.which(EDITORS[override]["command"][0]):
        return override
    
    # called from settings
    usage = settings.get("editor_usage")
    if not isinstance(usage, dict):
        usage = {}
    
    # a Checklist of rules to let editors be actually usa-blegive 
    usable = {
        name: count
        for name, count in usage.items()
        if name in EDITORS
        and isinstance(count, int)
        and count > 0
        and shutil.which(EDITORS[name]["command"][0])
        and (not EDITORS[name]["gui"] or has_display())
    }

    if usable:
        return max(usable, key=usable.get)

    return "nano"


def record_editor_use(name):
    usage = settings.get("editor_usage")
    if not isinstance(usage, dict):
        usage = {}

    count = usage.get(name, 0)
    if not isinstance(count, int):           
        count = 0

    usage[name] = usage.get(name, 0) + 1
    settings.set("editor_usage", usage)


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

    try:
        subprocess.run(["chmod", "+x", str(path)], check=False)
        print(f"Made executable: {path.name}")
    except FileNotFoundError:
        print("⚠️ Command not available: chmod")


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
        ".go": run_go_file,
        ".rs": run_rust_file,
    }
    runner = runners.get(path.suffix)
    if not runner:
        print("Unsupported file type. Supported: .py, .c, .cpp, .java, .js, .sh, .go, .rs")
        return

    runner(path)


class ZipExtractionError(Exception):
    """Raised when writing archive entries fails; anything written is undone first."""


def check_zip_member(info):
    """Return (relative parts, None) for a safe archive entry, or (None, reason)."""
    name = info.filename
    if "\0" in name:
        return None, "the name contains a null character"
    if "\\" in name:
        return None, "the name contains a backslash"
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None, "the path is absolute"

    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts:
        return None, "the name is empty"
    if ".." in parts:
        return None, "the path uses .. to leave the folder"
    for part in parts:
        if any(blocked in part for blocked in BLOCKED_NAME_PARTS if blocked != "/"):
            return None, "the name contains a blocked character"

    if info.flag_bits & 0x1:
        return None, "the entry is encrypted"

    file_type = stat.S_IFMT(info.external_attr >> 16)
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        return None, "links and special files are not allowed"

    return parts, None


def plan_zip_extraction(archive):
    """Check every entry first. Returns (entries, None) or (None, message)."""
    infos = archive.infolist()
    if not infos:
        return None, "the archive is empty"
    if len(infos) > MAX_ZIP_ENTRIES:
        return None, f"it has {len(infos)} entries (limit {MAX_ZIP_ENTRIES})"

    total_bytes = sum(info.file_size for info in infos)
    if total_bytes > MAX_ZIP_UNPACKED_BYTES:
        return None, (
            f"it would unpack to {total_bytes // (1024 * 1024)} MB "
            f"(limit {MAX_ZIP_UNPACKED_BYTES // (1024 * 1024)} MB)"
        )

    workspace = WORKSPACE_DIR.resolve()
    entries = []
    seen = set()
    for info in infos:
        parts, reason = check_zip_member(info)
        if reason:
            return None, f"unsafe entry '{info.filename}': {reason}"

        target = (workspace.joinpath(*parts)).resolve()
        if not target.is_relative_to(workspace) or target == workspace:
            return None, f"unsafe entry '{info.filename}': it resolves outside workspace/"
        if target in seen:
            return None, f"entry '{info.filename}' appears more than once"
        seen.add(target)

        is_dir = info.is_dir()
        if target.exists() and not (is_dir and target.is_dir()):
            return None, f"'{info.filename}' already exists in workspace/ and would be overwritten"
        entries.append((info, target, is_dir))

    return entries, None


def write_zip_entries(archive, entries):
    """Extract planned entries. Undo everything if any entry fails. Returns file count."""
    created = []
    written = 0
    try:
        for info, target, is_dir in entries:
            if is_dir:
                if not target.exists():
                    target.mkdir(parents=True)
                    created.append(target)
                continue

            for parent in reversed(target.parents):
                if parent == WORKSPACE_DIR.resolve() or parent.exists():
                    continue
                parent.mkdir()
                created.append(parent)

            # "xb" refuses to overwrite and never follows an existing link.
            with archive.open(info) as source, open(target, "xb") as destination:
                created.append(target)
                remaining = MAX_ZIP_UNPACKED_BYTES - written
                data = source.read(remaining + 1)
                if len(data) > remaining:
                    raise ValueError("the archive unpacks to more data than it declared")
                destination.write(data)
                written += len(data)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        for path in reversed(created):
            try:
                path.rmdir() if path.is_dir() else path.unlink()
            except OSError:
                pass
        raise ZipExtractionError(str(error)) from error

    return sum(1 for _, _, is_dir in entries if not is_dir)


def handle_unzip(words):
    if len(words) != 2:
        print("Please provide one archive name, for example: unzip project.zip")
        return

    path = get_safe_path(words[1])
    if not path:
        return
    if path.suffix.lower() != ".zip":
        print("Only .zip archives are supported.")
        return
    if not path.is_file():
        print(f"File does not exist in workspace: {path.name}")
        return

    try:
        with zipfile.ZipFile(path) as archive:
            entries, problem = plan_zip_extraction(archive)
            if problem:
                print(f"Blocked unsafe archive {path.name}: {problem}. Nothing was extracted.")
                return
            count = write_zip_entries(archive, entries)
    except ZipExtractionError as error:
        print(f"Could not extract {path.name}: {error}. Nothing was extracted.")
        return
    except zipfile.BadZipFile:
        print(f"Could not extract {path.name}: it is not a valid zip file. Nothing was extracted.")
        return
    except OSError as error:
        print(f"Could not read {path.name}: {error.strerror or error}.")
        return

    print(f"Extracted {count} file(s) from {path.name} into workspace/")


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
    if not shutil.which("ps"):
        print("⚠️ ps is not installed, so running processes information is unavailable.")
        return

    try:
        result = subprocess.run(["ps", "aux", "--sort=-%mem"], capture_output=True, text=True, check=False)
        lines = result.stdout.splitlines()[:11]  # header plus the 10 largest processes
        print("\n".join(lines))
    except FileNotFoundError:
        print("⚠️ ps is not installed, so running processes information is unavailable.")


def show_disk_usage():
    if shutil.which("df"):
        run_command(["df", "-h"])
        return

    try:
        usage = shutil.disk_usage("/")
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        print(f"Root filesystem (fallback): {used_gb:.1f}G used, {free_gb:.1f}G free, {total_gb:.1f}G total (df not installed)")
    except Exception:
        print("⚠️ Disk usage information is unavailable (df is not installed).")


def show_memory_usage():
    if shutil.which("free"):
        run_command(["free", "-h"])
        return

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            lines = meminfo.read_text().splitlines()
            mem_data = {}
            for line in lines:
                parts = line.split(":")
                if len(parts) == 2:
                    mem_data[parts[0].strip()] = parts[1].strip()
            total = mem_data.get("MemTotal")
            available = mem_data.get("MemAvailable", mem_data.get("MemFree"))
            if total and available:
                print(f"Memory (fallback from /proc/meminfo): Total: {total}, Available: {available} (free not installed)")
                return
        except OSError:
            pass

    print("⚠️ Memory usage information is unavailable (free is not installed).")


def show_system_uptime():
    if shutil.which("uptime"):
        run_command(["uptime"])
        return

    uptime_file = Path("/proc/uptime")
    if uptime_file.is_file():
        try:
            total_seconds = float(uptime_file.read_text().split()[0])
            hours, remainder = divmod(int(total_seconds), 3600)
            minutes, _ = divmod(remainder, 60)
            days, hours = divmod(hours, 24)
            if days:
                print(f"System uptime (fallback): {days} day(s), {hours} hour(s), {minutes} minute(s)")
            else:
                print(f"System uptime (fallback): {hours} hour(s), {minutes} minute(s)")
            return
        except (ValueError, OSError, IndexError):
            pass

    print("⚠️ System uptime is unavailable (uptime not installed).")


def show_kernel_info():
    if shutil.which("uname"):
        run_command(["uname", "-a"])
        return

    print(f"Kernel info (fallback): {platform.platform()}")


def show_cpu_info():
    if shutil.which("lscpu"):
        run_command(["lscpu"])
        return

    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            lines = cpuinfo.read_text().splitlines()
            model_lines = [
                line.split(":", 1)[1].strip()
                for line in lines
                if line.startswith("model name")
            ]
            if model_lines:
                print(f"CPU (fallback from /proc/cpuinfo): {model_lines[0]} ({len(model_lines)} core(s)) (lscpu not installed)")
                return
        except OSError:
            pass

    print("⚠️ CPU information is unavailable (lscpu is not installed).")


def show_current_user():
    if shutil.which("whoami"):
        run_command(["whoami"])
        return

    try:
        print(getpass.getuser())
    except Exception:
        user = os.environ.get("USER") or os.environ.get("LOGNAME")
        if user:
            print(user)
        else:
            print("⚠️ Current user information is unavailable.")


def show_hostname():
    if shutil.which("hostname"):
        run_command(["hostname"])
        return

    try:
        print(socket.gethostname())
    except Exception:
        print("⚠️ Hostname is unavailable.")


def show_os_info():
    if shutil.which("lsb_release"):
        run_command(["lsb_release", "-a"])
        return

    os_release = Path("/etc/os-release")
    if os_release.is_file():
        try:
            print(os_release.read_text().strip())
            return
        except OSError:
            pass

    if shutil.which("uname"):
        run_command(["uname", "-sro"])
        return

    print("⚠️ OS distribution information is unavailable.")


def show_network_info():
    if shutil.which("ip"):
        run_command(["ip", "addr", "show"])
        return

    if shutil.which("ifconfig"):
        run_command(["ifconfig"])
        return

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        print(f"Network info (fallback): Host: {hostname}, IP: {ip} (ip/ifconfig not available)")
    except Exception:
        print("⚠️ Network information is unavailable (ip and ifconfig not installed).")


def show_logged_in_users():
    if shutil.which("who"):
        run_command(["who"])
        return

    if shutil.which("w"):
        run_command(["w"])
        return

    user = os.environ.get("USER")
    if user:
        print(f"Logged in user (fallback): {user}")
    else:
        print("⚠️ Logged in users information is unavailable (who is not installed).")


def show_python_version():
    if shutil.which("python3"):
        run_command(["python3", "--version"])
        return

    print(f"Python {sys.version.split()[0]} (internal)")


def show_package_manager_info():
    managers = ("apt", "dnf", "pacman", "zypper", "apk")
    found = [manager for manager in managers if shutil.which(manager)]
    print("Detected package manager(s): " + ", ".join(found) if found else "No common package manager detected.")


def handle_version():
    model_files = ["intent_model.pkl", "vectorizer.pkl"]
    found = all((Path(PROJECT_DIR) / f).exists() for f in model_files)

    # whole custom printing stash
    lines = [
        f"E-SHELL v{__version__}",
        f"Python {platform.python_version()} ({sys.executable})",
        f"OS: {platform.platform()}",
        "",
        "Dependencies:",
        *[f"  {line}" for line in dependency_lines()],
        "",
        f"Model files: {'found' if found else 'MISSING'}",
        f"Project dir: {PROJECT_DIR}",
        usage_line(),
    ]
    print("\n".join(lines))

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
    if first_word == "make" and lowered_words[-1] == "executable":
        handle_make_executable(words)
        return
    if first_word == "run":
        handle_run_file(words)
        return
    if first_word in ("unzip", "extract"):
        handle_unzip(words)
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
    DEBUG = os.environ.get("ESHELL_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    print(DEBUG)

    if DEBUG: 
        print(f"[DEBUG] Predicted intent: {intent}")

    handlers = {
        "list_files": lambda: run_command(["ls"]),
        "current_dir": lambda: run_command(["pwd"]),
        "disk_usage": show_disk_usage,
        "memory_usage": show_memory_usage,
        "date_time": lambda: print(datetime.datetime.now()),
        "system_uptime": show_system_uptime,
        "kernel_info": show_kernel_info,
        "cpu_info": show_cpu_info,
        "current_user": show_current_user,
        "hostname": show_hostname,
        "open_firefox": lambda: launch_background(["firefox"]),
        "calculator": lambda: launch_background(["gnome-calculator"]),
        "os_info": show_os_info,
        "gpu_info": show_gpu_info,
        "battery_info": show_battery_info,
        "network_info": show_network_info,
        "ip_address": show_network_info,
        "logged_in_users": show_logged_in_users,
        "running_processes": show_running_processes,
        "environment_info": show_environment_info,
        "shell_info": lambda: print(os.environ.get("SHELL", "Unknown shell")),
        "python_version": show_python_version,
        "package_manager_info": show_package_manager_info,
        "fastfetch_info": show_fastfetch_info,
        "version": handle_version,
    }

    handler = handlers.get(intent)
    if handler:
        handler()
    else:
        print_unknown_feedback(text)
