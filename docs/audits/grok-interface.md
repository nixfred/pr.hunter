**Review of the three provided files only.** `pr_hunter.py` and the JSON contract are not in this bundle, so helper-side token handling, `gh` invocation, cache locking, and argparse behavior are called out as assumptions, not confirmed bugs.

Confirmed bugs are things these files already do wrong on their own. Protocol limitations are constraints of Omarchy/Quickshell/Herdr. Assumptions are failures that only happen if the helper’s JSON or CLI contract is weaker than the UI believes.

---

## Confirmed bugs

### 1. Medium — `Service.qml` / `scanProcess` and `actionProcess` stdio vs `onExited`

**Reproduction**
1. Make the helper print valid JSON on stdout, a warning on stderr, and exit 1 (or exit 0 with stderr).
2. Let the 15s timer fire, or click Refresh / Preview.

**What goes wrong**
Stdout, stderr, and `onExited` are independent. Order is not defined.

- Scan success JSON can set `lastError` to `""`, then `onExited` sees a non-zero code and `!root.lastError` and replaces it with `Project scan failed. Check Herdr and gh authentication.`
- Scan success can set a clean snapshot, then stderr `onStreamFinished` overwrites `lastError` with a truncated warning.
- Action JSON can set `message` from `result.message`, then stderr overwrites it.

**Impact**
False failures on the bar and in the panel; real helper errors can be replaced by the last 400 chars of a deprecation warning. Users will chase Herdr/`gh` auth that is not broken.

**Fix**
Handle the result only in `onExited`. Read stdout/stderr there, prefer JSON from stdout, use stderr only if stdout is empty, and treat exit code as secondary to a parsed `error` field. Do not write `lastError`/`message` from three separate handlers.

---

### 2. Medium — `Service.qml` / `act()` vs `refresh()`

**Reproduction**
1. Wait for the 15s scan to start (`refreshing` true).
2. Open a project and click Open & process, Preview brief, Open session, Save mapping, or Cancel queue.

**What goes wrong**
`refresh()` bails if either process is running. `act()` only bails if `actionProcess` is running, so an action starts on top of a live scan. When the action finishes, `onExited` calls `refresh(false)`, which no-ops if the scan is still running.

**Impact**
Two helper processes at once (cache races live in the helper, see assumptions). After dispatch/map/cancel, the snapshot can stay stale until the next timer tick, so queue state and counts in the panel do not match what just happened.

**Fix**
Serialize all helper work on one queue (or one `Process`). `act()` must wait for or cancel the scan. After an action, refresh must actually run.

---

### 3. Medium — `Service.qml` / `Process` has no timeout

**Reproduction**
Block `python3` (stuck `gh`, waiting Herdr socket, helper deadlock). Watch the timer and the Refresh / Preview buttons.

**Impact**
`refreshing` or `busy` stays true forever. The timer cannot start another scan. Dispatch, preview, map, and IPC `refresh`/`preview` all no-op. The only recovery is restarting the shell.

**Fix**
Add a watchdog (for example 30–60s). On timeout, kill the process, set a clear `lastError`/`message`, and allow the next scan.

---

### 4. Medium — `HunterPanel.qml` / `counts`, `dispatch`, list delegate, detail column

**Reproduction**
Feed `snapshot.projects` with a project missing `repos`, `agents`, `paths`, or `job` (truncated JSON, older helper, or an error object). Open the panel.

**What goes wrong**
These paths assume the full shape with no guards:

- `filtered` does `p.repos.map(...)`
- `waitingProjects` does `p.pr_count + p.issue_count`
- list delegate does `row.modelData.job.status` and `row.modelData.job.message`
- `dispatch` does `project.repos.length` and `project.agents.length`
- `detail` does `project.agents.length` and `project.paths.length`
- Cancel queue does `root.current.job.status`

A single bad project throws inside a binding or delegate and can blank the whole list, not just that row.

**Impact**
Panel renders empty or stuck after a partial helper response, even if other projects are valid. The scan error path in `Service.qml` still assigns `root.snapshot = result` whenever `result.error` is absent.

**Fix**
Normalize in `Service.qml` when applying a snapshot: default `repos`, `agents`, `paths` to `[]`, `job` to `{status:"", message:""}`, and counts to `0`. In QML, optional-chain before `.length` / `.status`.

---

### 5. Low–Medium — `Service.qml` / `helper`

**Reproduction**
Install the plugin under a path with a space or other URL-reserved character (`~/Projects/PR Hunter/...`). Open the shell so `scanProcess` starts.

**What goes wrong**
`Qt.resolvedUrl("pr_hunter.py")` returns a `file://` URL. Stripping `^file://` leaves percent-encoding (`%20`) and does not decode it. `python3` is then given a path that does not exist.

**Impact**
Scan/action fail on any non-trivial install path. The panel shows the generic scan failure. This is easy to miss if the current checkout has no spaces.

**Fix**
Resolve to a filesystem path with `QUrl` (`toLocalFile()` / Quickshell’s file-path helper) or `decodeURIComponent` after stripping the scheme. Handle `file://localhost/...` as well.

---

### 6. Low–Medium — `Service.qml` / `act()` argument passing

**Reproduction**
In Details, set Repository checkout to `-h`, `--force`, or `--key`, then click Save mapping.

**What goes wrong**
Path/key/pane/scope are passed as the next argv after `--path` / `--key` / `--pane` / `--scope`. A value that starts with `-` is a classic argparse footgun: it can be taken as a flag instead of a value.

**Impact**
Mapping can no-op, print argparse help on stderr (then treated as `message`/`lastError`), or change helper flags. Key/pane from Herdr are less likely to start with `-`; the mapping field is user-controlled.

**Fix**
Use `--path=${path}` form, or put `--` before values. Reject paths that start with `-` in QML. The helper should use `argparse` `nargs`/`metavar` patterns that accept leading dashes as values.

---

### 7. Low — `HunterPanel.qml` / `IpcHandler.preview`

**Reproduction**
Call `omarchy-shell nixfred.pr-hunter preview <key>` before `bar.shell.serviceFor("nixfred.pr-hunter")` is available (startup, or service failed to load).

**What goes wrong**
`refresh()` null-checks `root.service`. `preview()` does not: after `detail(p)` it calls `root.service.act(...)`.

**Impact**
IPC throws, preview never runs, and depending on Quickshell’s IPC error handling the call can look like a hung client. Same class of issue on Cancel queue (`root.service.act` with no null check), though that button is only visible with live project data.

**Fix**
`if (!root.service) return` before `act`. Guard Cancel the same way.

---

### 8. Low — `HunterPanel.qml` header / `lastError || message`

**Reproduction**
Cause a scan warning that sets `lastError`. Then run Preview or Dispatch so `message` becomes `Done` or a handoff string.

**Impact**
The header prefers `lastError`, so successful action text never appears until a later scan clears it. Sticky stderr races (finding 1) make this worse.

**Fix**
Show `lastError` and `message` as separate lines, or clear `lastError` when an action returns a successful JSON object.

---

### 9. Low — `HunterPanel.qml` / `act` callers when `busy`

**Reproduction**
Click Preview brief, then immediately click Open & process, Cancel queue, or Save mapping.

**Impact**
`act()` returns with no UI change. The first action’s `message` (`Loading the complete work brief…`) stays up. Users retry and think dispatch/cancel ran.

**Fix**
Disable all action buttons from a single `busy` flag (Cancel already ignores it). If ignored, set `message` to `Already working…`.

---

### 10. Low — `install.py` / `edited_config`

**Reproduction**
Install on a live config that already has `nixfred.pr-hunter` in the bar and has no `disabledPlugins` key.

**Impact**
`desired == original` is false because the function always writes `disabledPlugins: []`. The installer applies a config change it did not need. That is an extra layout-capable apply, which is exactly the class of reload the retry comment is trying to survive.

**Fix**
Only set `disabledPlugins` if the key already exists or the plugin id is actually in the list.

---

### 11. Low — `install.py` / `main` apply failure

**Reproduction**
Make `omarchy shell config-edit apply` fail with empty stderr (CLI prints only to stdout, or a signal).

**Impact**
`raise SystemExit(result.stderr)` exits with a blank message. `returned non-zero exit status` in stderr is also treated as retryable, so some permanent failures are retried twice and then blamed on “kept changing.”

**Fix**
Exit with `stderr or stdout or returncode`. Narrow retryable matches to the compare-and-set phrases you already listed (`changed since`, `changed during`, `not responding`, `timed out`).

---

### 12. Low — `HunterPanel.qml` / panel sizing

**Reproduction**
Load the bar module and inspect the plugin’s slot.

```qml
implicitWidth: barButton.implicitWidth
implicitHeight: barButton.implicitHeight
WidgetButton { anchors.fill: parent; ... }
```

**Impact**
Parent implicit size comes from the child; the child is stretched to the parent. If `WidgetButton` reports implicit size from its laid-out width, the bar entry can collapse to 0×0 or a tiny hit target. This is a known QML cycle; whether it bites depends on `WidgetButton`.

**Fix**
Do not fill-anchor the button. Size the `Panel` from the button’s implicit size and let the button sit unanchored (or only center it).

---

## Protocol limitations (not bugs in this code)

- **Local IPC is unauthenticated.** `IpcHandler` on `nixfred.pr-hunter` is the Omarchy/Quickshell session bus. Any process in the session can `open`, `refresh --force`, `preview`, `select`, and read `status` (project labels, PR/issue counts, agent status, errors). That is how `omarchy-shell nixfred.pr-hunter open` is meant to work. Do not treat it as a remote API. Rate-limiting `refresh(true)` belongs in the helper if `gh` is expensive.
- **`manageIpc: false` plus a manual `IpcHandler`** matches the “we own the IPC surface” Omarchy pattern. Not a bug.
- **`install.py` compare-and-set** (snapshot, deepcopy, `--allow-layout-change`, refuse to replay a stale snapshot) matches the live shell config API. Refusing to replace a different install at the same plugin id is correct.
- **15s `Timer` while the panel is closed** is a standing session cost. That is a product choice. The footer’s “projects every 15 sec” matches this file; “GitHub every 5 min” is not implemented here.
- **List-row click dispatches** when there is exactly one agent and at least one repo. The copy says that is intended. It is still a serious misclick path (panel closes and a handoff is sent). Product risk, not a logic error.
- **Scope filters are UI-only in `counts()`.** The bar badge uses helper `pr_count + issue_count` and ignores All / Yours / Upstream. Inconsistent, but not a broken filter in `counts()` itself.

---

## Assumptions (need `pr_hunter.py` / JSON schema to confirm)

- **Helper JSON types.** `waitingProjects` uses `p.pr_count + p.issue_count > 0`. If those fields are strings, `"0" + 0` becomes `"00"` and the badge lights up for empty projects.
- **Concurrent scan + action** is only safe if the helper locks its cache and does not interleave writes. These QML files currently allow that overlap.
- **`--key` / `--pane` / `--scope` / `--path` handling** in argparse, and whether `command` is a closed subcommand list. QML passes argv correctly (no shell), so injection requires the helper to `os.system` / interpolate those values.
- **Mapping path** is any string the user types. Whether that can overwrite files, follow symlinks, or be used as a git remote is entirely the helper’s problem.
- **GitHub 5-minute cache** is claimed in the footer and not present in these files. If `scan` hits GitHub every 15s, that is a helper bug (rate limits), not a QML bug.
- **`onExited: function(code)`** assumes Quickshell passes a numeric exit code as the first argument. If the signal is `(exitCode, status)` this is correct; if the signature differs, finding 1’s exit-code branch is wrong in a second way.
- **`Process` + `StdioCollector` delivers complete stdout** on `onStreamFinished`. If a large brief is truncated, preview JSON parse fails and the user only sees `The action could not complete.`

---

## What looks solid

- Helper is invoked as an argv list, not a shell string.
- Preview/dispatch/map/focus commands from the UI are literals, not user strings (`IpcHandler` does not expose a generic `act`).
- User-facing GitHub/Herdr strings that are rendered as `Text` mostly set `textFormat: Text.PlainText`.
- Installer uses list-form `subprocess`, validates the plugin, creates a directory symlink only when the id is free or already points at this tree, and does not replay an old snapshot after a hot reload.
- `dispatch` from the list refuses to guess a pane when `agents.length !== 1`.
- Scope “upstream” correctly uses `!r.own` in `counts()`.

I did not run tests or execute these files, per the request.