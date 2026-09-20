# Verification

## The default view showed mostly other people's work (2026-09-20)

- Reported as wrong information. The counts were correct against GitHub; the
  framing was not. Of 31 listed rows, 3 were Fred's own work, 8 showed an
  upstream repository's counts under his project's name (`trackpad.pulse` read
  "4 open PRs" while `nixfred/trackpad.pulse` had none and `davefano` had four),
  and 20 were Herdr workspaces with no repository mapped at all.
- The panel now opens on **Your repos** and lists only projects that need
  attention. Same data, 31 rows down to 3, and the bar badge counts your own
  waiting work rather than every remote, so badge and list agree.
- **Show all** restores the full 64. Verified through the new `showAll` and
  `setScope` IPC functions, which also make the header buttons scriptable:
  default reports 3 rows, Show all reports 64.
- A saved project whose folder has gone missing is no longer parked in the work
  list forever; the header names the count instead. Two are currently missing.
- The card now fits its content. With three rows the list scrolls 0 pixels
  (it was 36 short when the inset was hand-added instead of using
  `fittedContentHeight`), and under Show all the list scrolls inside its own box
  while the page does not, per Law 17.

## Strangers rank first, and delivery became exact (2026-09-17)

- A reader suggested weighting whether a human you do not know opened the thing.
  Measured across all 41 repositories before building anything: 17 such items sat
  on repositories Fred owns, against 69 on upstream repositories he does not.
  Weighting strangers everywhere would simply re-float the busiest upstream
  repositories, so the signal is counted only where he is the owner, which is
  what the suggestion described. No bots appeared anywhere in that survey; they
  are excluded by author type regardless.
- GitHub returns author association in the batched query already being sent, so
  the signal costs no extra request. A forced scan of 41 repositories takes 5.5 s
  and the cache holds 20 KB.
- The same sample exposed a real fault in the delivery count. It had been
  estimated by counting receipts whose URL began with the repository, capped at
  the open total. The ledger also holds receipts for items closed since, so blip
  read as fully delivered while four open pull requests, two of them from
  strangers, had never been sent. Delivery is now counted against the items that
  are open right now. Verified by hand against the ledger: blip's four
  undelivered items are pulls 96, 98, 99 and 100, and the scan now reports
  exactly four pending.
- 70 Python tests pass, six new: author association filtering with a bot, a
  deleted account and a collaborator; one stranger outranking 80 open items;
  strangers ignored on a repository you do not own; a stranger already handed to
  an agent dropping out; delivery counted against currently open items; and the
  estimate still used for a repository busier than the sample. The QML service
  check, the native Herdr transport check and the isolated launch check pass.
  Live panel and Details inspected in screenshots.

## Ranking counted the wrong number (2026-09-11)

- Imprint sat at the top showing nine open items while a click reported nothing
  to send. Both were true: all nine were delivered to its agent at 11:34, and the
  list was ranking raw open counts. Ranking now uses items not yet handed off,
  measured against the delivery ledger, and a fully delivered project says so on
  its row. Verified live: Imprint, infomarchy and blip moved below every project
  with unsent work, including three holding a single item.
- 64 Python tests pass, including a project with nine delivered items ranking
  below one with two untouched items, and delivery being capped at what is still
  open (items closed since delivery, and repository name case, must not distort
  the count). The QML service check, the native Herdr transport check and the
  isolated launch check pass. Screenshot inspected.

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
