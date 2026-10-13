# E-SHELL

E-SHELL is a small Python-based shell that lets a user interact with a Linux terminal using simple natural-language phrases instead of remembering exact shell commands.

For example, a user can type:

```text
disk usage
cpu info
kernel info
who am i
```

and E-SHELL predicts the user's intent, then runs the matching safe system-information command.

## Why E-SHELL is useful

E-SHELL is useful because it:

- makes common terminal tasks easier for beginners
- shows how a simple machine-learning classifier can be connected to real commands
- demonstrates intent classification using `TF-IDF` and `LogisticRegression`
- provides a safer way to experiment with natural-language shell control by using only non-destructive commands

It is a good learning project for anyone interested in Python, machine learning, Linux commands, or building shell-style tools.

## How E-SHELL works

E-SHELL has a small pipeline:

```text
User input
   ↓
assistant.py
   ↓
model.py predicts the intent
   ↓
commands.py runs the matching safe command
```

### Main files

| File | Purpose |
|---|---|
| `assistant.py` | Starts the E-SHELL session, reads user input, and passes it to the command handler. |
| `commands.py` | Contains the supported safe actions that can be executed. |
| `intents.json` | Stores example phrases for each supported intent. |
| `workspace/` | Safe folder for files that can be edited, made executable, or run. |
| `train.py` | Trains the classifier from the phrases in `intents.json`. |
| `intent_data.py` | Checks `intents.json` for problems before training. |
| `evaluation_phrases.json` | Held-out test phrases, kept separate from `intents.json`, used only to measure the model. |
| `evaluate.py` | Scores the saved model on the held-out phrases and writes a report. |
| `docs/model-evaluation.md` | The latest evaluation report. |
| `model.py` | Loads the saved model and predicts the intent for new user input. |
| `vectorizer.pkl` | Saved TF-IDF vectorizer created during training. |
| `intent_model.pkl` | Saved trained intent classifier. |
| `run.sh` | Helper script for starting E-SHELL. |
| `HOW_TO_RUN.txt` | Short plain-text run instructions. |

## Supported safe commands

E-SHELL supports informational commands plus intentionally limited file actions.

| Intent / input | What it does |
|---|---|
| `list_files` | Shows files in the current directory with `ls`. |
| `current_dir` | Shows the current directory with `pwd`. |
| `disk_usage` | Shows storage usage with `df -h`, or Python disk usage calculation as fallback. |
| `memory_usage` | Shows memory usage with `free -h`, or `/proc/meminfo` as fallback. |
| `date_time` | Prints the current date and time. |
| `system_uptime` | Shows how long the system has been running with `uptime`, or `/proc/uptime` as fallback. |
| `kernel_info` | Shows kernel/system details with `uname -a`, or `platform` as fallback. |
| `cpu_info` | Shows CPU details with `lscpu`, or `/proc/cpuinfo` as fallback. |
| `current_user` | Shows the logged-in user with `whoami`, or `getpass`/`USER` as fallback. |
| `hostname` | Shows the machine name with `hostname`, or `socket.gethostname` as fallback. |
| `os_info` | Shows Linux distribution details with `lsb_release -a`, `/etc/os-release`, or `uname` as fallback. |
| `gpu_info` | Shows GPU-related entries from `lspci` when available. |
| `battery_info` | Reads non-destructive battery status from `/sys/class/power_supply`. |
| `network_info` / `ip_address` | Shows network interfaces with `ip addr show`, or `ifconfig`/host lookup as fallback. |
| `logged_in_users` | Shows logged-in users with `who`, `w`, or `$USER` as fallback. |
| `running_processes` | Shows the ten largest processes by memory usage with `ps` (with clear notice if missing). |
| `environment_info` | Prints selected environment variables such as `USER`, `HOME`, and `PATH`. |
| `shell_info` | Shows the current shell from the `SHELL` environment variable. |
| `python_version` | Shows the installed Python version with `python3 --version`. |
| `package_manager_info` | Detects common package managers such as `apt`, `dnf`, and `pacman`. |
| `fastfetch_info` | Runs `fastfetch` if installed; otherwise falls back to `uname`, `lscpu`, `free`, and `df`. |
| `touch filename` or `create file filename` | Creates one file in the current project directory. |
| `mkdir foldername` or `create folder foldername` | Creates one folder in the current project directory. |
| `cp source destination` or `copy source to destination` | Copies one existing file to another simple filename in the current project directory. |
| `edit filename` or `open filename` | Opens `workspace/filename` in the configured default editor (nano by default). Set `E_SHELL_DEFAULT_EDITOR` to `nano`, `vim`, `micro`, `helix`, `emacs`, `gedit`, or `atom` to choose another. |
| `open filename in <editor>` | Opens the file in nano, vim, micro, helix, emacs, gedit, or atom. GUI editors launch in the background. |
| `make filename executable` | Runs `chmod +x` for a validated file inside `workspace/`. |
| `run filename` | Runs supported code files inside `workspace/` after asking for confirmation the first time. |
| `unzip archive.zip` or `extract archive.zip` | Safely extracts a `.zip` from `workspace/` into `workspace/` after checking every entry. |
| `open_firefox` | Opens Firefox. |
| `calculator` | Opens the calculator application. |

## Safety: intentionally narrow file operations

E-SHELL blocks destructive or privileged commands such as:

```text
rm
rmdir
mv
chmod
chmod 777
chown
sudo
shutdown
reboot
kill
mkfs
dd
```

Those commands are blocked on purpose because they can delete data, alter permissions, stop the machine, or damage disks. The only permission change supported is the narrow phrase `make filename executable`, which runs `chmod +x` on a validated file inside `workspace/`.

For file actions, E-SHELL:

- accepts only simple names in the current project directory
- rejects names containing `/`, `..`, `~`, `*`, `?`, `&`, `|`, `;`, `$`, `` ` ``, `>`, or `<`
- asks for missing arguments instead of guessing
- uses Python APIs or `subprocess.run([...])` argument lists rather than passing raw user input to `shell=True`
- opens and runs files only inside `workspace/`
- allows only the supported editor allowlist: `nano`, `vim`, `micro`, `helix`, `emacs`, `gedit`, and `atom`
- asks before running a file for the first time because code execution can be unsafe
- runs code with a 10 second timeout and captures stdout and stderr

### Safe ZIP extraction

`unzip archive.zip` (or `extract archive.zip`) reads a `.zip` file that is already inside `workspace/` and extracts it into `workspace/`. The whole archive is checked before anything is written, and it is refused with a message if any entry is unsafe:

- absolute paths, drive letters, `..` segments, backslashes, null characters, or shell symbols in a name
- symbolic links and special files, and encrypted entries
- an entry that would resolve outside `workspace/`, for example through an existing link
- an entry that would overwrite an existing file, or the same path appearing twice
- more than 200 entries, or more than 20 MB once unpacked (measured from the archive's contents, so a small archive that expands hugely is refused)

Files are never overwritten, extracted files are not made executable, and nothing is run or approved by extracting. If writing fails part-way, everything written so far is removed. Files inside sub-folders can be extracted, but `run`, `edit` and `make ... executable` still only work on files directly inside `workspace/`.

Supported run types:

| Extension | Command used safely |
|---|---|
| `.py` | `python3 filename` |
| `.c` | `gcc filename -o filename_without_ext`, then the compiled program |
| `.cpp` | `g++ filename -o filename_without_ext`, then the compiled program |
| `.java` | `javac filename`, then `java ClassName` |
| `.js` | `node filename` |
| `.sh` | `bash filename` |
| `.go` | `go run filename` |
| `.rs` | `rustc filename -o filename_without_ext`, then the compiled program |

Examples:

```text
touch notes.txt
create file notes.txt
mkdir examples
create folder examples
cp notes.txt backup.txt
copy notes.txt to backup.txt
edit hello.py
open hello.py in nano
open hello.py in vim
make script.sh executable
run hello.py
run hello.go
run hello.rs
unzip project.zip
```

E-SHELL also includes a confidence threshold in `model.py`. If the model is not confident enough about a phrase, it returns `unknown` instead of forcing an unrelated command. In that case E-SHELL runs nothing and replies with a short message suggesting `help` or a rephrased request. Phrases that merely start with a command word (for example `make the computer do something`) get the same response. The `[DEBUG] Predicted intent` line is hidden by default; set `ESHELL_DEBUG=1` to show it.

## How to run E-SHELL

1. Open a terminal.
2. Move into the project directory:

```bash
cd E-SHELL
```

3. If you changed `intents.json`, retrain the model:

```bash
venv/bin/python train.py
```

`train.py` resolves its input and output paths relative to its own script location, so you can also invoke it from any working directory:

```bash
venv/bin/python /path/to/E-SHELL/train.py
```

Before training, `intents.json` is checked. Malformed JSON, empty phrase lists, blank or non-text phrases, fewer than two intents, and the same phrase listed under different intents (ignoring case) stop training with a message that names the problem. Nothing is saved when the data is invalid.

Use `venv/bin/python`, not plain `python3`, because the E-SHELL dependencies such as `scikit-learn` are installed inside the virtual environment.

4. Start E-SHELL:

```bash
venv/bin/python assistant.py
```

You can also use the helper script:

```bash
./run.sh
```

To choose the editor used by `edit filename` or `open filename`, set
`E_SHELL_DEFAULT_EDITOR` to a supported editor. For example:

```bash
E_SHELL_DEFAULT_EDITOR=micro ./run.sh
```

The default is `nano`. Editors must already be installed and available on
`PATH`; E-SHELL will suggest installing the requested editor or choosing
another supported one if it cannot find it.

## How to run the tests

E-SHELL includes a small standard-library test suite for safe file handling, fallback command routing, and the new intents:

```bash
venv/bin/python -m unittest discover -s tests -v
```

`tests/test_languages_and_zip.py` covers running `.go` and `.rs` files and the ZIP extraction safety checks.

`tests/test_routing_and_safety.py` covers intent routing (each predicted intent reaches the right handler, and unknown or file-action intents run nothing), blocked commands, filename and path validation, and the confirm-before-run rules.

To exit E-SHELL:

```text
exit
```

## Evaluating the model

`evaluate.py` measures the saved model on phrases it was **not** trained on (`evaluation_phrases.json`), so the score reflects new wording and not memorised examples:

```bash
venv/bin/python evaluate.py                                      # print the report
venv/bin/python evaluate.py --markdown docs/model-evaluation.md  # also save it
```

The report ([docs/model-evaluation.md](docs/model-evaluation.md)) lists overall accuracy with a 95% interval, results for each intent, the most confused intent pairs, the supported phrases the model did not recognise, and whether out-of-scope requests were refused. It separates two kinds of miss: a phrase that is **not recognised** (E-SHELL shows the help message) and a phrase answered with the **wrong command** (the costly one).

Latest results on 150 hand-written phrases (135 supported requests, 15 out-of-scope requests):

- 95 of 135 (70.4%) supported requests were understood.
- 8 (5.9%) got the wrong command, and 32 (23.7%) were not recognised.
- 15 of 15 out-of-scope requests were correctly refused.
- Without the confidence threshold the top-ranked intent would be right for 114 of 135 (84.4%), so the threshold trades some understanding for fewer wrong commands.
- Intents with the fewest training phrases do worst: `calculator` (2 training phrases), `open_firefox` (3 training phrases) were never understood, and phrases such as "open the browser" were pulled towards `edit_file`, which has far more training phrases.

These numbers come from a small hand-written set. One phrase moves the overall figure by less than a point, so treat small differences between runs as noise.

### Adding examples without overstating the model

1. Add the phrase to the right intent in `intents.json`. Training checks the file and stops with a message if the same phrase is listed under two intents.
2. Retrain with `venv/bin/python train.py`.
3. To measure the effect, add a few **differently worded** phrases for that intent to `evaluation_phrases.json`. Never copy a training phrase into it: `evaluate.py` refuses to run if a test phrase was also trained on. Out-of-scope requests that might be confused with the new intent go under `"unknown"`.
4. Re-run `venv/bin/python evaluate.py --markdown docs/model-evaluation.md` and commit the updated report with your change.

When you report results:

- Quote the score on held-out phrases, never on the training phrases. The model has seen those, so the score only shows it remembered them.
- Give the number of phrases. With a set this small, a change of a few points is not evidence of improvement.
- Report the **wrong command** and **out-of-scope refused** figures as well as the headline accuracy. Do not lower `MIN_CONFIDENCE` just to raise accuracy: it recovers some phrases but lets more wrong commands through.
- Do not present the probabilities as certainty. They are small because they are spread across every intent, and they are not calibrated: 0.30 does not mean a 30% chance of being right.
- Keep intents roughly balanced. A large intent such as `edit_file` can absorb phrases that belong elsewhere.
- Accuracy never replaces the safety checks. Blocked commands, name validation and the confirmation before running code apply no matter what the model predicts.

## Example phrases to try

```text
disk usage
os info
gpu info
battery info
network info
ip address
logged in users
running processes
environment info
shell info
python version
package manager info
fastfetch info
touch notes.txt
create file notes.txt
mkdir examples
create folder examples
cp notes.txt backup.txt
copy notes.txt to backup.txt
edit hello.py
open hello.py in nano
open hello.py in vim
make script.sh executable
run hello.py
```

## Proof that the model works

The screenshots below show the trained model correctly recognizing several supported inputs and safely rejecting an unknown one.

### Disk usage intent

E-SHELL predicts `disk_usage` and shows filesystem storage information:

![Disk usage prediction](docs/screenshots/disk-usage.png)

### CPU information intent

E-SHELL predicts `cpu_info` and prints detailed processor information:

![CPU info prediction](docs/screenshots/cpu-info.png)

### Kernel information and unknown input handling

E-SHELL predicts `kernel_info` for a kernel query, and it also rejects unsupported text as `unknown` instead of running an unsafe or unrelated command:

![Kernel info and unknown handling](docs/screenshots/kernel-and-unknown.png)

### Workspace editor and run safety

E-SHELL shows the new help text, uses the safe workspace rules, asks before running code, and keeps unsupported command forms blocked:

![Workspace editor and run safety](docs/screenshots/workspace-editor-run.png)

### Clean exit

E-SHELL exits normally when the user types `exit`:

![E-SHELL exit](docs/screenshots/assistant-exit.png)

## Current limitations

- The model is trained on a small number of example phrases, so its vocabulary is still limited.
- Measured results, including the phrases it misses, are in [docs/model-evaluation.md](docs/model-evaluation.md).
- It is designed for Linux systems and uses Linux-specific commands.
- It is a lightweight classifier-based shell, not a large conversational AI model.

## Future improvements

Possible next steps include:

- adding automated tests for safety validation
- improving help output further
- increasing the number of training examples
- improving unknown-command detection further
- adding tests for intent prediction and command routing
