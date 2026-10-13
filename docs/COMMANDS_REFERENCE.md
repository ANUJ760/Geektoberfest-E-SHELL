# E-SHELL Commands Reference

This reference documents every intent and file-operation command supported by E-SHELL, along with example phrases, the action each command performs, and any external Linux tool it requires.

> **Tip:** Type `help` inside E-SHELL to see a quick list of example phrases.

---

## System Information Commands

These commands are recognised by the intent classifier and executed through safe, read-only handlers in `commands.py`.

### 1. `list_files`
- **Description:** Lists the files and folders in the current project directory.
- **Example phrases:** `list files`, `show files`, `display files`, `files`, `directory listing`.
- **Action:** Runs `ls` via `subprocess.run(["ls"])`.
- **Required tools:** `ls` (coreutils).

### 2. `current_dir`
- **Description:** Prints the current working directory path.
- **Example phrases:** `current directory`, `where am i`, `present directory`, `pwd`, `working directory`.
- **Action:** Runs `pwd` via `subprocess.run(["pwd"])`.
- **Required tools:** `pwd` (coreutils).

### 3. `disk_usage`
- **Description:** Shows filesystem storage usage.
- **Example phrases:** `disk usage`, `storage info`, `disk space`, `free disk space`, `show disk usage`.
- **Action:** Runs `df -h`. Falls back to Python `shutil.disk_usage("/")` if `df` is not installed.
- **Required tools:** `df` (coreutils, optional). Fallback uses Python standard library.

### 4. `memory_usage`
- **Description:** Displays system memory (RAM) usage.
- **Example phrases:** `memory usage`, `ram usage`, `free memory`, `memory info`, `show ram`.
- **Action:** Runs `free -h`. Falls back to reading `/proc/meminfo` if `free` is not installed.
- **Required tools:** `free` (`procps` package, optional). Fallback reads `/proc/meminfo`.

### 5. `date_time`
- **Description:** Prints the current local system date and time.
- **Example phrases:** `date`, `time`, `current time`, `current date`, `what time is it`.
- **Action:** Pure Python `datetime.datetime.now()`.
- **Required tools:** None (Python standard library).

### 6. `system_uptime`
- **Description:** Reports how long the system has been running.
- **Example phrases:** `system uptime`, `uptime`, `show uptime`, `computer uptime`, `how long has the system been running`.
- **Action:** Runs `uptime`. Falls back to reading `/proc/uptime` if `uptime` is not installed.
- **Required tools:** `uptime` (`procps` package, optional). Fallback reads `/proc/uptime`.

### 7. `kernel_info`
- **Description:** Displays the Linux kernel version, system architecture, and OS build details.
- **Example phrases:** `kernel info`, `system kernel`, `kernel details`, `linux kernel`, `uname info`.
- **Action:** Runs `uname -a`. Falls back to Python `platform.platform()` if `uname` is not installed.
- **Required tools:** `uname` (coreutils, optional). Fallback uses Python standard library.

### 8. `cpu_info`
- **Description:** Details processor architecture, model name, and core counts.
- **Example phrases:** `cpu info`, `processor details`, `show cpu`, `processor info`, `cpu model`.
- **Action:** Runs `lscpu`. Falls back to reading `/proc/cpuinfo` if `lscpu` is not installed.
- **Required tools:** `lscpu` (`util-linux` package, optional). Fallback reads `/proc/cpuinfo`.

### 9. `current_user`
- **Description:** Prints the username of the current terminal session.
- **Example phrases:** `current user`, `who am i`, `whoami`, `logged in user`, `my username`.
- **Action:** Runs `whoami`. Falls back to Python `getpass.getuser()` or `$USER` / `$LOGNAME` environment variables.
- **Required tools:** `whoami` (coreutils, optional). Fallback uses Python standard library.

### 10. `hostname`
- **Description:** Prints the network hostname of the current machine.
- **Example phrases:** `hostname`, `computer name`, `machine name`, `device name`, `show hostname`.
- **Action:** Runs `hostname`. Falls back to Python `socket.gethostname()`.
- **Required tools:** `hostname` (optional). Fallback uses Python standard library.

### 11. `os_info`
- **Description:** Displays Linux distribution name, release, and codename.
- **Example phrases:** `os info`, `operating system info`, `linux version`, `distribution info`, `show distro`.
- **Action:** Runs `lsb_release -a` if installed; falls back to reading `/etc/os-release`; then falls back to `uname -sro`.
- **Required tools:** `lsb_release` (optional), `/etc/os-release` (fallback), `uname` (fallback).

### 12. `gpu_info`
- **Description:** Lists connected GPU and graphics display controllers.
- **Example phrases:** `gpu info`, `graphics card info`, `show gpu`, `video card info`, `which gpu do i have`.
- **Action:** Inspects output of `lspci` for `vga`, `3d`, and `display` entries.
- **Required tools:** `lspci` (`pciutils` package, optional). Reports a clear notice if missing.

### 13. `battery_info`
- **Description:** Reads battery charge percentage and charging status.
- **Example phrases:** `battery info`, `battery status`, `battery level`, `battery percentage`, `power status`.
- **Action:** Direct filesystem read of `/sys/class/power_supply/BAT*`.
- **Required tools:** None (Linux sysfs access). Reports `No battery information found.` if absent.

### 14. `network_info` / `ip_address`
- **Description:** Lists network interfaces, link status, and assigned IP addresses.
- **Example phrases:** `network info`, `show network`, `ip address`, `what is my ip`, `show ip`.
- **Action:** Runs `ip addr show`; falls back to `ifconfig`; then falls back to `socket.gethostbyname()`.
- **Required tools:** `ip` (`iproute2` package, optional) or `ifconfig` (`net-tools`, optional). Fallback uses Python standard library.

### 15. `logged_in_users`
- **Description:** Shows currently logged in user sessions.
- **Example phrases:** `logged in users`, `who is logged in`, `active users`, `current sessions`, `who command`.
- **Action:** Runs `who`; falls back to `w`; then falls back to the `$USER` environment variable.
- **Required tools:** `who` or `w` (coreutils, optional). Fallback uses `$USER`.

### 16. `running_processes`
- **Description:** Displays the 10 highest memory-consuming running processes.
- **Example phrases:** `running processes`, `show processes`, `process list`, `top memory processes`, `what is running`.
- **Action:** Runs `ps aux --sort=-%mem` and shows the header plus the top 10 lines.
- **Required tools:** `ps` (`procps` package). Reports a clear notice if missing.

### 17. `environment_info`
- **Description:** Displays selected environment variables: `USER`, `HOME`, `SHELL`, `LANG`, `TERM`, `PATH`.
- **Example phrases:** `environment info`, `environment variables`, `show environment`, `env info`.
- **Action:** Direct Python inspection of `os.environ`.
- **Required tools:** None.

### 18. `shell_info`
- **Description:** Prints the user's active login shell path.
- **Example phrases:** `shell info`, `show shell`, `which shell`, `current shell`, `what shell am i using`.
- **Action:** Reads `os.environ.get("SHELL")`.
- **Required tools:** None.

### 19. `python_version`
- **Description:** Prints the installed Python 3 interpreter version.
- **Example phrases:** `python version`, `show python version`, `python3 version`, `check python version`.
- **Action:** Runs `python3 --version`. Falls back to reporting `sys.version` if `python3` is not on `PATH`.
- **Required tools:** `python3` (optional). Fallback uses the running interpreter.

### 20. `package_manager_info`
- **Description:** Probes and lists detected Linux package managers.
- **Example phrases:** `package manager info`, `which package manager`, `show package manager`, `detect package manager`.
- **Action:** Probes paths for `apt`, `dnf`, `pacman`, `zypper`, and `apk` using `shutil.which`.
- **Required tools:** None required; detects installed managers.

### 21. `fastfetch_info`
- **Description:** Runs the `fastfetch` system summary tool. Falls back to core safe commands if `fastfetch` is not installed.
- **Example phrases:** `fastfetch info`, `run fastfetch`, `system summary`, `neofetch style info`.
- **Action:** Runs `fastfetch`. Fallback runs `uname -a`, `lscpu`, `free -h`, and `df -h`.
- **Required tools:** `fastfetch` (optional).

### 22. GUI Launchers: `open_firefox` / `calculator`
- **Description:** Spawns Firefox or GNOME Calculator in a detached background process.
- **Example phrases:** `open firefox`, `start browser`, `open calculator`, `start calculator`.
- **Action:** `subprocess.Popen(["firefox"])` or `subprocess.Popen(["gnome-calculator"])`.
- **Required tools:** `firefox` or `gnome-calculator` (optional GUI desktop apps).

---

## File Operation Commands

File operations are triggered by direct keyword parsing (not the intent classifier). All operations are confined to safe paths and are non-destructive.

| Command syntax | Action | Safety rules |
| :--- | :--- | :--- |
| `touch <name>` / `create file <name>` | Creates an empty file. | Name must be simple (no path separators or shell metacharacters). Created in the project root. |
| `mkdir <name>` / `create folder <name>` | Creates a folder. | Name must be simple. Created in the project root. |
| `cp <src> <dst>` / `copy <src> to <dst>` | Copies a file. | Source must exist. Destination must be a simple name. Uses `shutil.copy2`. |
| `edit <file>` / `open <file>` | Opens a workspace file in the default editor. | Restricted to `workspace/<file>`. Default editor is `nano`; override with `E_SHELL_DEFAULT_EDITOR`. |
| `open <file> in <editor>` | Opens a workspace file in the specified editor. | Restricted to `workspace/<file>`. Allowed editors: `nano`, `vim`, `micro`, `helix`, `emacs`, `gedit`. |
| `make <file> executable` | Adds executable permission. | Restricted to `workspace/<file>`. Runs `chmod +x`. |
| `run <file>` | Runs a code file in the workspace. | Restricted to `workspace/<file>`. Asks for confirmation before the first run. 10-second timeout. |
| `unzip <archive.zip>` / `extract <archive.zip>` | Extracts a safe ZIP archive into `workspace/`. | Restricted to `workspace/<archive.zip>`. Refuses directory traversal (`..`, leading `/`), symlinks, encrypted archives, and archives exceeding 200 entries or 20 MB. |

### Supported run types

| Extension | Command used |
| :--- | :--- |
| `.py` | `python3 <file>` |
| `.c` | `gcc <file> -o <output>`, then runs the compiled binary |
| `.cpp` | `g++ <file> -o <output>`, then runs the compiled binary |
| `.java` | `javac <file>`, then `java <ClassName>` |
| `.js` | `node <file>` |
| `.sh` | `bash <file>` |
| `.go` | `go run <file>` |
| `.rs` | `rustc <file> -o <output>`, then runs the compiled binary |

---

## Blocked Commands

The following commands are blocked on purpose to prevent data loss, permission changes, or system damage:

`rm`, `rmdir`, `mv`, `sudo`, `kill`, `shutdown`, `reboot`, `chmod`, `chown`, `dd`, `mkfs`, `chmod 777`.

The only permission change supported is the narrow phrase `make <file> executable`, which runs `chmod +x` on a validated file inside `workspace/`.

---

## Filename Safety Rules

- Only simple names in the current project directory are accepted.
- Names containing `/`, `..`, `~`, `*`, `?`, `&`, `|`, `;`, `$`, `` ` ``, `>`, or `<` are rejected.
- Editing, `chmod +x`, and running are limited to files inside `workspace/`.
- E-SHELL uses `subprocess.run([...])` argument lists rather than `shell=True`.

---

## Unknown Commands

If the classifier is not confident enough about a phrase it returns `unknown`. E-SHELL runs nothing and suggests typing `help` or rephrasing. Set `ESHELL_DEBUG=1` to see the raw predicted intent for troubleshooting.
