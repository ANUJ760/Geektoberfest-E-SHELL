# Linux Compatibility and Command Fallback Guide

E-SHELL is designed for Linux environments. Depending on the Linux distribution (e.g., Ubuntu, Debian, Arch, Fedora, Alpine) or installation type (desktop, server, minimal container), certain command-line utilities may not be pre-installed.

This guide outlines each external utility invoked by E-SHELL, the environments where it might be missing, and the built-in fallbacks and safety measures provided.

---

## Command Matrix and Fallbacks

| Feature / Intent | Primary Utility | Potential Missing Scenarios | Fallback Behavior / Safety Mechanism |
| :--- | :--- | :--- | :--- |
| **OS Information** (`os_info`) | `lsb_release -a` | Minimal installs, Alpine, Arch, containers | Automatically falls back to reading `/etc/os-release` if `lsb_release` is not in `$PATH`. |
| **System Summary** (`fastfetch_info`) | `fastfetch` | Most standard installations (optional tool) | Automatically detects missing `fastfetch` and falls back to running safe system queries: `uname -a`, `lscpu`, `free -h`, and `df -h`. |
| **GPU Information** (`gpu_info`) | `lspci` | Minimal containers, headless servers without `pciutils` | Probes `shutil.which("lspci")`. If unavailable, prints `⚠️ lspci is not installed, so GPU information is unavailable.` without crashing. |
| **Battery Status** (`battery_info`) | None (direct sysfs) | Desktops without battery, virtual machines, cloud instances | Reads `/sys/class/power_supply/BAT*`. If no batteries exist, reports `No battery information found.` gracefully. |
| **Package Managers** (`package_manager_info`) | `apt`, `dnf`, `pacman`, `zypper`, `apk` | Varies by distribution | Probes known package managers using `shutil.which` and displays whichever is detected, or reports none detected. |
| **Network Information** (`network_info`, `ip_address`) | `ip addr show` | Very minimal systems without `iproute2` | Safely caught with `⚠️ Command not available: ip`. |
| **Running Processes** (`running_processes`) | `ps aux --sort=-%mem` | Extremely minimal embedded containers without `procps` | Displays top 10 memory-consuming processes. |
| **Logged-in Users** (`logged_in_users`) | `who` | Minimal containers without coreutils | Catches missing command gracefully. |
| **Current User** (`current_user`) | `whoami` | Extremely minimal container | Non-destructive execution via `run_command`. |
| **Hostname** (`hostname`) | `hostname` | Minimal container environments | Non-destructive execution via `run_command`. |
| **Kernel / System Info** (`kernel_info`) | `uname -a` | Standard on virtually all Linux systems | Non-destructive execution via `run_command`. |
| **Disk Usage** (`disk_usage`) | `df -h` | Standard Linux coreutils | Safe read-only execution. |
| **Memory Usage** (`memory_usage`) | `free -h` | Minimal container without `procps` | Safe read-only execution. |
| **CPU Info** (`cpu_info`) | `lscpu` | Minimal container without `util-linux` | Safe read-only execution. |
| **Environment Info** (`environment_info`) | None | Always available | Directly inspects Python `os.environ` (`USER`, `HOME`, `SHELL`, `LANG`, `TERM`, `PATH`). |
| **Current Shell** (`shell_info`) | None | Always available | Directly inspects the `SHELL` environment variable. |
| **Python Version** (`python_version`) | `python3 --version` | Always available (requires Python 3 to run E-SHELL) | Executes `python3 --version` safely. |
| **Date & Time** (`date_time`) | None | Always available | Formatted directly via Python's standard `datetime` module. |
| **Web Browser** (`open_firefox`) | `firefox` | Headless servers, non-GUI environments | Uses background process launcher. If Firefox is missing, reports `⚠️ Command not available: firefox`. |
| **Calculator** (`calculator`) | `gnome-calculator` | Non-GNOME desktop environments, headless servers | Uses background process launcher. If missing, reports `⚠️ Command not available: gnome-calculator`. |

---

## Workspace Code Execution and Toolchains

E-SHELL allows running supported code files from the `workspace/` folder. Each language runner relies on the corresponding toolchain being installed on the host system:

| File Extension | Toolchain Required | Missing Toolchain Behavior |
| :--- | :--- | :--- |
| `.py` | `python3` | Reports `⚠️ Command not available: python3` if not found. |
| `.c` | `gcc` | Reports compiler errors or `⚠️ Command not available: gcc` if missing. |
| `.cpp` | `g++` | Reports compiler errors or `⚠️ Command not available: g++` if missing. |
| `.java` | `javac`, `java` | Reports compiler errors or `⚠️ Command not available: javac` if missing. |
| `.js` | `node` | Reports `⚠️ Command not available: node` if Node.js is not installed. |
| `.sh` | `bash` | Reports `⚠️ Command not available: bash` if Bash is not installed. |

---

## Distribution Specific Notes

- **Debian / Ubuntu**: Most utilities (`df`, `free`, `uname`, `lscpu`, `ip`, `nano`) are pre-installed. `fastfetch` and `lspci` (part of `pciutils`) can be installed via `apt install fastfetch pciutils`.
- **Fedora / RHEL / CentOS**: Package manager is `dnf`. `pciutils` provides `lspci`.
- **Arch Linux**: Package manager is `pacman`. `util-linux`, `procps-ng`, and `iproute2` are standard.
- **Alpine Linux (Docker)**: Uses `musl` libc and `busybox`. Some flags such as `ps aux --sort=-%mem` or `lsb_release` may differ or require installing `procps` and standard packages.
