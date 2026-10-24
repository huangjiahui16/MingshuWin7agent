# MingShu Win7 (明枢Win7)

**English**  |  [简体中文](README.zh-CN.md)

A desktop agent that runs on **Windows 7 SP1**. You type one sentence in plain language and it works on your PC by itself — tidying files, reading documents, checking the network, running commands. Every step can be watched, approved, or stopped.

- **Standard library only** — the UI is drawn with tkinter. No Electron, no Node, no .NET, no pip packages.
- **A real agent** — it plans several steps, calls tools, looks at the results, then decides what to do next and reports back.
- **Safety first** — three kernel-level resource walls, an approval gate, "ask whenever it leaves the workspace", an audit log, and a circuit breaker.
- **Runs on old hardware** — single machine, no GPU, 4GB RAM, spinning disk, 32-bit system.

> The model runs in the cloud (any OpenAI-compatible endpoint). Your PC only executes tools and enforces the safety rules.
> No vendor lock-in: DeepSeek, Qwen, Kimi, OpenAI, local Ollama or LM Studio all work.

## Screenshots

![Main window](https://github.com/user-attachments/assets/86bbc125-2a08-4040-aef3-2e441e57ee32)

![Chat and tool cards](https://github.com/user-attachments/assets/312e2606-1590-4d93-872b-b51c6e86d2e9)

![Settings](https://github.com/user-attachments/assets/7487fde0-d5b3-49dc-a7bf-b60a97ec8773)

![Notification and attachment preview](https://github.com/user-attachments/assets/76484037-aede-44c3-9f01-c88cdbd60644)

---

## 1. Requirements

| Item | Requirement |
|---|---|
| OS | Windows 7 SP1 or later (32-bit and 64-bit) |
| Python | **3.8** to run from source (the last version supporting Win7). Not needed if you use the exe |
| RAM | 4GB or more (the app itself is capped at 300MB) |
| GPU | None |
| Network | Must reach the model endpoint you configure |

---

## 2. Quick start

### Option A — download the exe (easiest)

Get it from the **Releases** page:

- `明枢Win7.exe` — 64-bit Windows
- `明枢Win7-x86.exe` — 32-bit Windows

Double-click it. On first run it creates a `data\` folder next to the exe (settings, chats and logs live there). Open **Settings → Model API** and paste your API key.

### Option B — run from source

```bat
:: 1) Install Python 3.8 (tick "Add Python to PATH")
:: 2) Copy the config templates
copy docs\assistant.example.ini data\assistant.ini
copy docs\api.md.example api.md
:: 3) Put your API key in data\assistant.ini (or in Settings after launch)
:: 4) Start
start-gui.bat
```

Console mode: `start-cli.bat` (no window, good for scripts).

---

## 3. Configuration

### Settings window

Click **Settings** and you can change the endpoint, API key, model, proxy, thinking level, tool output size, max steps, workspace folder, permission level, long-term memory, and the two force switches.

The two switches (**Force skills** / **Force long-term memory**) apply **immediately — no restart**. Only the task that is already running keeps the old setting until it finishes.

### `api.md` — model presets

`api.md` in the program folder is a plain, hand-editable list of endpoints. The Settings window reads it and writes back to it.

```ini
# Active: deepseek

[deepseek]
label = DeepSeek (cheap, good Chinese)
base_url = https://api.deepseek.com/v1
api_key = sk-your-key
model = deepseek-flash

[qwen]
label = Qwen (Alibaba DashScope)
base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
api_key = 
model = qwen-plus

# Comment a block out with # to keep it as a spare
#[local]
#base_url = http://127.0.0.1:1234/v1
#model = qwen2.5-7b-instruct
```

Pick a preset → **Load preset** fills the fields. **Test connection** sends a tiny `max_tokens=1` request and reports the result in the panel.

### `data\assistant.ini` — advanced

```ini
[llm]
base_url = https://api.deepseek.com/v1
api_key = 
model = deepseek-flash
thinking = off          ; off/low/high/max

[agent]
workspace =             ; folder the agent may touch; empty = whole PC
perm_gear = ask         ; auto/ask/strict/locked
max_steps = 6
mem_limit_mb = 300      ; memory wall
max_procs = 4           ; max child processes
cpu_wall = thread       ; thread = lower the worker thread only / process = whole process IDLE

[memory]
enabled = true
```

---

## 4. How to use it

### Three modes

| Mode | What it can do |
|---|---|
| **Agent** | Everything: list folders, read files, search, run commands, write files, open files, fetch web pages |
| **Plan** | Read-only: it can look but never change anything — good for analysis first |
| **Ask** | Chat only: no tools at all, cheapest in tokens |

### Four permission levels

| Level | Behaviour |
|---|---|
| 🟢 Auto | L0/L1 run silently; L2/L3 still ask you |
| 🟡 Ask | Up to L2 runs silently; L3 (system changes) needs explicit approval |
| 🟠 Strict | Only read-only actions; everything else is refused |
| 🔴 Locked | Refuse everything |

**Anything outside the workspace always asks you**, no matter which level is active — and long-term memory can't override that rule.

### Keyboard

| Key | Action |
|---|---|
| `Enter` | Send |
| `Shift+Enter` | New line |
| `Esc` | Stop the running task |
| `Ctrl+K` | Command palette |
| `Ctrl+Alt+Q` | Stop from any window (for when the mouse is busy) |
| `Ctrl+V` | Paste **files** or a **screenshot** from the clipboard — it becomes an attachment with a thumbnail (hover for a bigger preview) |

In the chat log, **double-click a path or an English word to select and copy the whole token**. The right-click menu also offers copy message / copy line / select all.

### Corner notifications

When the window is minimised or in the background, a small card slides in at the bottom-right:

- ✓ green — task finished (with a short summary)
- **? amber — needs your approval** (e.g. something outside the workspace); it stays until you deal with it
- ! red — something failed
- i blue — a scheduled task finished

Click the card to bring the main window back. Nothing pops up while you are actively looking at the window.

### Long-term memory

- Say "remember: I hand in a weekly report every Friday afternoon" and it is stored
- You can also edit `记忆.md` in the program folder (one entry per line, `#` starts a comment)
- Each chat has its own memory; deleting a chat deletes what that chat learned
- Turn it off entirely with **Force long-term memory** in Settings (applies at once, nothing is injected or saved)

### Skills

Each folder under `skills\` is one skill. The model reads the `description` in `SKILL.md` to decide when to use it. Seven ship with the project:

| Skill | When it kicks in |
|---|---|
| `win7-files` | Tidying files, batch renaming, cleanup, finding large or duplicate files |
| `office-docs` | Reading/writing Word, Excel, PowerPoint; pulling text and tables out of documents |
| `net-diag` | No internet, endpoint unreachable, DNS/proxy/TLS troubleshooting |
| `system-check` | System info, compatibility checks, tracking down slowdowns |
| `git-github` | Committing code, cleaning a repo, preparing a GitHub upload |
| `win7-pitfall` | Win7 gotchas before writing scripts (encoding, paths, DPI, TLS) |
| `pdf-extract` | Pulling text out of PDFs and telling you if it is a scanned image |

**Add your own**: create `skills\your-skill\SKILL.md`:

```markdown
---
name: my-skill
description: One sentence saying when this skill should be used (the model relies on this line)
---

# Body: steps, commands, things to watch out for
```

**Remove one**: delete the folder. No restart needed — the list is rescanned on the next turn.

### Chinese / English UI

There is a language button just above **Chat** in the left sidebar. One click switches the whole interface (help page, buttons, hints, corner notifications) to English, **and the model starts answering in English**. The choice is saved in `data\ui_state.json` and restored next launch. Chinese is the default on first run.

---

## 5. Safety design — why it won't wreck your machine

| Mechanism | What it does |
|---|---|
| **Memory wall** | Job Object: if the app passes 300MB the kernel kills it; max 4 child processes |
| **CPU wall** | Worker threads drop to idle priority (-15), so you always win when you touch the mouse |
| **I/O wall** | Worker threads switch to background I/O mode; foreground programs stay first |
| **Approval gate** | Sits in the tool registry — the model can't bypass it. Anything outside the workspace asks you |
| **Audit log** | Every tool call is recorded (tool, level, approved or denied) |
| **Circuit breaker** | More than 5 dangerous actions, 200 file writes, or 60 tool calls → read-only until you step in |
| **Snapshots** | Files are backed up before writes and deletes; you can restore them |
| **Always stoppable** | Stop button in the UI, plus `Ctrl+Alt+Q` from any window |

---

## 6. Folder layout

```
明枢Win7.exe / 明枢Win7-x86.exe   release binaries (if you build them)
start-gui.bat / start-cli.bat     launchers for source runs
api.md                            model presets (put your key here, never commit it)
记忆.md                            long-term memory (one entry per line)
src\                              source code
  wb_app.py                         UI (hand-drawn with tkinter)
  win7_assistant.py                 engine (loop / tools / permissions / protocol)
  win7_limits.py                    resource walls + timing
assets\                           icons
skills\                           skill library
docs\                             docs, templates, perf report, upload checklist
tests\                            regression tests (python tests\test_name.py)
data\                             created at runtime: settings, chats, logs, pasted images
```

Everything inside `data\` is runtime state (`assistant.ini`, `sessions\`, `logs\`, `facts.json`, `perf.jsonl`). Deleting it resets the app — **but you lose your chats and memory too**.

---

## 7. Troubleshooting

**Can't reach the model / TLS handshake failed**
TLS 1.2 is requested explicitly. On an old Win7 machine also: (1) sync the system clock; (2) install the root certificate update (KB931125); (3) install the TLS 1.2 patch (KB3140245); (4) switch endpoint or check your proxy.

**Certificate verification failed**
Usually a wrong system clock or outdated root certificates. The app tells you which one it looks like.

**Antivirus blocks the exe**
PyInstaller binaries are unsigned, so 360/Windows Defender often block them the first time. Add an exclusion.

**Taskbar shows the wrong icon**
Windows caches old icons. Restart Explorer, or run `ie4uinit.exe -show`.

**Feels slower than the Windows 11 client**
Run `python docs\bench_perf.py` and look at the three-way split. In our measurement local disk work was about 1% of total time — almost all of it is waiting for the model. Reduce tool rounds instead of optimising disk code.

**Burning through tokens**
Lower `max_steps`, set thinking to `off`, turn off **Force skills**, and cut the tool output limit to about 1000 characters.

---

## 8. Building the exe yourself

```bat
:: needs Python 3.8 + PyInstaller
python -m pip install pyinstaller==5.13.2
python -m PyInstaller --onefile --windowed --name MingShuWin7 ^
  --icon assets\mingshu.ico --add-data "assets;assets" ^
  --paths src --distpath dist --workpath build src\wb_app.py
```

The binary lands in `dist\` and is self-contained.

---

## 9. License

MIT. Use it, change it, ship it. The icon was generated by the project author with an AI tool and is released with the project (non-commercial use only for the artwork). Respect the terms of whichever model provider you point it at.
