# Verification

## Clicks that could not feed work (2026-09-11)

- 62 Python tests and the QML service check pass, including new coverage for the
  resend path, the scope hint, the focus explanations, the action log and the
  checkout suggestion. The QML check now asserts that a panel-closing command
  raises exactly one outcome notification and that Send again reaches the helper
  as `--force`.
- The native Herdr transport check and the isolated launch check still pass. No
  live agent received a test prompt: the dispatch path was exercised with delivery
  stubbed, against a copy of the real state directory.
- Diagnosed live on vic. Of 16 listed projects, 11 dispatch on click and 5 could
  only ever focus, because no GitHub repository resolves from their panes' working
  directories. Two of those sit in a non-repository directory, one is a local-only
  repository with no remote. That is the reported "opens the session but feeds
  nothing", and those rows now say so before a click and suggest a checkout where
  one can be found. Verified in a screenshot of the live panel.

## Version 1.1.0

- 56 Python regression tests cover the existing dispatch protections plus saved
  projects, stable identities after reopening, optional Herdr, exact launch paths,
  terminal reuse, double-click suppression and inherited Herdr environment cleanup.
- The isolated native launch check starts a real Herdr server from a stopped state,
  creates one workspace in a directory containing spaces and shell metacharacters,
  reuses it, closes and reopens it, and verifies the saved project key stays stable.
- The same check removes Herdr from its isolated PATH and records the default-terminal
  launch arguments and working directory using a launcher shim. This validates the
  fallback without touching a production session or sending an agent prompt.
- The native Herdr transport check, real QML service check and Omarchy manifest
  validation pass. Opening a new project creates a shell, not an AI agent.

## Version 1.0.1

See the [Grok audit and resolution](docs/audits/2026-09-09.md). The updated release
passes 41 Python tests, the real QML service test with an isolated fake helper,
and the native isolated Herdr transport test. The installed panel and service both
report 1.0.1, discover 24 live projects and report no scan errors. An unmapped
project was opened in its existing Herdr workspace with no prompt sent; prior
focus was restored. The shell needed a reload to clear its QML cache. Fresh
live and saved configuration matched before/after, with all bar settings/order
preserved. Both README SVGs were rendered
and visually inspected. No live agent receives test prompts.

## Initial installation (1.0.0)

Verified on 2026-09-09 with Herdr 0.8.2 / protocol 20 and the installed Omarchy shell.

- 17 backend regression tests pass: remote parsing, pagination/PR classification,
  busy/blocked agents, replacement identity, expired/closed/changed projects,
  duplicate item versions across worktrees, ambiguous delivery, definite rejection,
  repository scopes, untrusted task data, and Lua/legacy window focus.
- The native isolated Herdr test passes using a compiled stdin recorder, with
  no LLM or real repository work: workspace discovery, exact agent identity,
  focus, prompt receipt, and discovery of a subsequently created space.
- Live discovery found 24 Herdr spaces. Twenty-two were mapped to GitHub after
  adding the plugin's remote and the verified Power Pulse/SONOS path overrides.
  CogMesh is a remote terminal without a locally detected agent; Now Playing
  has no GitHub mapping. Both remain visible and can be opened from Details.
- Read-only live previews enumerated all seven blip PRs plus two issues and
  the Tailscale fork's PR despite that repository having issues disabled.
- Exact terminal focus was verified against the real Herdr client process,
  then the previously active window was restored. This host uses Lua dispatch.
- The actual panel loaded the complete brief, reached the last project, retained
  its scroll offset over a refresh, and was visually checked in overview and
  Details. The live blip handoff receipt also recorded nine items sent to its
  existing Claude session; it subsequently reported working.
- Omarchy manifest validation passed. QML syntax/import resolution was checked
  with the shell import path; dynamic Omarchy QObject properties produce static
  lint warnings, so the running shell was the final rendering check.
- A fresh live/disk comparison verified that installation added exactly one bar
  entry and preserved all existing settings and ordering. The final shell reload
  preserved the same configuration. No Herdr production server restart occurred.

Two environment-specific problems found during validation were corrected:
the first temporary Herdr server isolated its socket but shared saved-session
storage; the production live state remained intact and was re-saved natively,
restoring all 24 spaces and 23 agent references. The test now isolates every XDG
storage directory and asserts an empty initial session. Also, the shell retained
old QML component/directory caches across rescans, so final UI activation needed
one shell reload after verifying live settings equaled disk.

Receipts indicate prompt acceptance, not successful completion of the requested
repository work. Automatic monitoring and queued delivery run while the Omarchy
plugin is enabled. Remote SSH/tmux agent dispatch is not implemented.
