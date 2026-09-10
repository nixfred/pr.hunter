# Verification

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
