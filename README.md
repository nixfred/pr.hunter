# PR Hunter

![PR Hunter overview with example projects and handoffs](docs/images/overview.svg)

An Omarchy menu-bar plugin that watches GitHub PRs and issues for Herdr projects
and saved local folders. Click a project to open its Herdr workspace, starting
the session if needed. **No Herdr installed? Your default terminal opens in the
project directory.** With an existing local agent, a click can also send a detailed
work brief. It supports Claude, Codex and other agents recognized by Herdr.

![Project discovery, GitHub monitoring and Herdr handoff flow](docs/images/workflow.svg)

## Use

- Click the Git branch icon and project count in the bar.
- Click any project row to open its Herdr workspace. With one local
  agent and a mapped repository, the click also assigns new/updated items.
  Other rows still open the project; use Details to choose an agent or mapping.
- If a terminal is already attached, it is focused. Otherwise the plugin opens
  your default terminal attached to that Herdr session.
- Closed projects stay listed and monitored. Clicking one reuses a matching
  workspace or creates one in its saved directory, starting Herdr if necessary.
  If Herdr is missing or cannot start, it opens the default terminal there.
- **Add project** saves a local folder, including on machines without Herdr.
  In Details, **Open terminal** explicitly opens a regular terminal even when
  Herdr is installed. It reuses a terminal previously opened by PR Hunter when
  its foreground process still occupies that directory and its window is identifiable.
- **All remotes / Your repos / Upstream** chooses the queue sent by a click.
  “Your repos” means repositories owned by the account authenticated in `gh`.
- Counts are **open GitHub items**, not unfinished agent tasks. They fall when
  PRs/issues close or merge, within five minutes or when you press Refresh.
  The bar badge counts projects with open items across all remotes.
  **Last handoff** is a historical receipt and does not shrink as items close.
- **Details** shows each repository, counts, agent choices, the last handoff,
  and a **Preview brief** action. Preview fetches all open items without sending.
- **Open project** opens or focuses the project without assigning work.
- Opening a closed project starts a shell. Start your preferred agent inside
  Herdr, then click again to send work; PR Hunter does not start replacement agents
  or type work briefs into ordinary shells.
- A busy, blocked or unknown agent receives a queued handoff only after it is
  ready. **Cancel queue** cancels a pending handoff. Queues expire after 24 hours.
- If multiple agents occupy a project, select one in Details before sending.
- Projects without a GitHub checkout remain visible. **Save mapping** associates
  a project with its actual local checkout when its terminal started elsewhere.

The brief lists repository paths/remotes and every selected issue/PR number,
title, URL, update time and draft status. It directs the agent to read discussions,
review diffs and CI, reproduce problems, group duplicates, implement suitable
fixes, run checks, commit/push to the intended user repository and report an
outcome for every item. Upstream changes are assessed for the user's fork.
Merging, closing items, deployments, releases and GitHub comments/reviews need
separate user authorization. GitHub content is explicitly untrusted evidence.

## Install

Requires Linux, Omarchy's plugin-capable shell, Python 3.10+, Git,
`xdg-terminal-exec` and an authenticated GitHub CLI (`gh auth status`).
Herdr is **optional**; session discovery and agent handoffs are tested with
Herdr 0.8.2 (socket protocol 20). No Python
packages, access tokens in settings, web server or separate system service.

```sh
git clone https://github.com/nixfred/pr.hunter.git
cd pr.hunter
python3 install.py
```

The installer links this checkout into `~/.config/omarchy/plugins/nixfred.pr-hunter`
and adds one visible bar entry. It uses a **fresh live** configuration snapshot
and a compare-and-set update, retaining all other entries and their order.
Keep the checkout in place. Python changes are picked up on the next scan.
After QML edits, rescan with `omarchy-shell shell rescanPlugins`; shell builds
that retain QML's component cache may require a shell reload for same-file edits.

Disable without removing code or state:

```sh
omarchy plugin disable nixfred.pr-hunter
```

Disabling stops the background scanner and queue delivery. Re-enable with
`python3 install.py`. Pending queues resume if still valid; cancel them first
if you do not want them resumed.

## Discovery and storage

Every 15 seconds the plugin discovers all **running local named Herdr sessions**,
then reads their live workspace/pane/agent snapshots. New projects are included
automatically and remembered when their sessions close. Saved folders are also
monitored without Herdr. It resolves Git roots from the panes' directories and de-duplicates
GitHub fetch remotes. GitHub counts are cached for five minutes, with manual
Refresh and a one-minute retry after errors. Errors remain visible; old counts
are not silently replaced with zero. Clicks and previews fetch complete,
paginated open-item lists. Partial repository failures are reported in the UI
and brief; only successfully fetched items are assigned. A failed Herdr discovery
pauses affected handoffs instead of treating a missing snapshot as a closed project.
GitHub ownership is rechecked for handoffs and refreshed at least every five minutes.
Draft PRs are included but the brief makes them review-only.

All discovered Herdr projects are visible, including unmapped projects and ordinary
terminal panes. Standalone terminal windows are not automatically discovered;
add their project folders with **Add project**.
An SSH/tmux session without a locally detected Herdr agent (for example a remote
shell inside a pane) can be focused but is not prompted. Run Herdr and this
integration on the remote machine, or use a supported local agent, to enable
that handoff. Arbitrary remote shells are never treated as agent input boxes.

Machine-specific mappings live in `~/.config/pr-hunter/config.json`, keyed by
`session-name:workspace-label`:

```json
{
  "mappings": {
    "default:My Project": {"paths": ["/absolute/path/to/checkout"]}
  }
}
```

Multiple paths can be set in this file when a space covers several repositories.
Paths are read as data, not shell commands. Automatic discovery needs no mapping.
Renaming a manually mapped space requires saving the mapping under its new name.

Private saved-project records, snapshots, cached GitHub counts, dispatch receipts and Markdown briefs
live in `~/.local/state/pr-hunter/` (respects XDG overrides). These files are never
committed to this repository. Queues are pinned to pane, terminal and agent-session
identity and cancelled if the project closes, its repository mapping changes or
the agent is replaced. The same item version is not dispatched twice, even across
multiple open worktrees. Updated items are eligible again when explicitly clicked.

Delivery receipts are written before sending. An ambiguous transport failure is
shown as uncertain and **never automatically retried**. Inspect that session, then use **Acknowledge receipt** to unblock new work.
Acknowledgment keeps the recorded item versions protected against duplicate
submission. It does not retry them or claim that the work completed.
“Sent” means the prompt was accepted, not that the agent completed the work.

Window focus uses the Herdr client's actual terminal process ancestry and its
named session, not a guessed terminal title. When no attached window is found,
it launches `herdr session attach` in the default terminal. Saved projects reopen
in their original named Herdr session; newly added folders use `default`.
A new workspace receives the saved directory explicitly. For projects with several
paths, the first path is the launch directory. Missing directories produce an error
so a moved checkout can be corrected in Details. Directory names are passed as
arguments, including spaces and shell metacharacters. Opening never starts an AI agent.

Regular terminals use `xdg-terminal-exec --dir=…` and a project-specific app ID.
On Hyprland, a matching window is reused only when its process ancestry and foreground
directory agree. If the terminal does not expose that identity, another click may
open a new window. Immediate double clicks are debounced.

## Verification and command line

```sh
python3 -m unittest discover -s tests -v
python3 tests/check_qml.py    # real QML + fake helper, requires Quickshell
python3 tests/check_herdr.py  # temporary Herdr server + harmless input recorder; requires cc
python3 tests/check_launch.py # cold Herdr start, reopening and no-Herdr fallback; isolated state
omarchy plugin validate .
python3 pr_hunter.py scan
omarchy-shell nixfred.pr-hunter status
omarchy-shell nixfred.pr-hunter open
```

`scan` returns project keys. `preview --key KEY` prints the complete brief;
`focus --key KEY` opens the project in Herdr or the default terminal;
`terminal --key KEY` explicitly opens a regular terminal;
`add --path /absolute/path/to/project` saves a folder;
`dispatch --key KEY --scope mine --pane PANE`
assigns work; `cancel --key KEY` cancels queued work. Unlike preview, `scan` also
services previously authorized queues. No work is assigned merely by installation.

References: [Herdr socket API](https://herdr.dev/docs/socket-api/),
[GitHub issue listing (includes pull requests)](https://docs.github.com/en/rest/issues/issues#list-repository-issues).

## Audit

Version 1.0.1 received a [Grok audit and finding-by-finding resolution](docs/audits/2026-09-09.md).
Version 1.1.0 adds saved projects, session creation and the regular-terminal fallback,
with 56 Python regression tests, isolated native Herdr transport and launch checks,
and an actual QML service test. See [verification details](VERIFICATION.md).
Both README graphics are original SVG illustrations
with example names and counts, not screenshots of private sessions.

Herdr protocol 20 has no atomic “submit only to this occupant if still idle”
parameter. PR Hunter checks identity and readiness immediately before prompting,
but a replacement or state change in the small gap between those RPCs remains
an upstream protocol limitation. Delivery records favor avoiding duplicate input.
Briefs and deduplication records are retained locally; do not delete a brief while
an agent may still need it. They are never included in the public repository.
