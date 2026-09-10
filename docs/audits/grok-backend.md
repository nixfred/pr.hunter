I'll read only `pr_hunter.py` and audit it for concrete bugs from the source itself.**Confirmed bugs first.** Protocol-dependent risks are at the end. Line numbers refer to `pr_hunter.py` as read.

## Confirmed bugs

### 1. GitHub login is cached forever (account switch is wrong)

**Severity:** High  
**Function:** `refresh_repos` (lines 161–162), used by `scan` and `action`  
**Reproduction:** Run `scan` once (writes `github.json` with `login`). Switch `gh` accounts. Run `scan --force` and `dispatch --scope mine` / `--scope upstream`.  
**Impact:** `if not cache.get("login")` never refetches after the first success. `--force` only bypasses per-repo intervals, not login. After an account change:

- `select_repos` mines/upstreams against the **old** user
- `r["own"]` and `upstream_count` stay wrong
- a dispatch can send the other account’s queue, or skip the new account’s repos

Repo rows eventually refresh (60s on error, 300s on success). Login does not.

**Fix:** Always resolve login (at least on `--force`, on a TTL, or when `gh api user` differs from cache). If it changed, drop or mark stale every `cache["repos"]` row and redo ownership. Fail closed if login cannot be confirmed, rather than reusing a previous account.

---

### 2. `sending` / `uncertain` jobs cannot be cancelled or retried; crash mid-send sticks forever

**Severity:** High  
**Function:** `send_job` (382–402), `process_queue` (409–411), `action` cancel/dispatch (481–493)  
**Reproduction:**

1. Dispatch so `send_job` writes `status: "sending"` and `ledger["sent"]` **before** `agent.prompt` (explicit comment at 383).
2. Kill the process during the RPC, or make the RPC raise `Failure`/`OSError` (`uncertain`).
3. `cancel` is a no-op unless status is `queued`. `dispatch` returns “already pending” for `queued`/`sending`/`uncertain`. `process_queue` only continues `queued` jobs. Nothing expires `sending`/`uncertain` (24h expiry is queued-only).

**Impact:**

- Delivered or not, those item versions stay in `ledger["sent"]`, so a later job will skip them.
- A crash after the pre-send write leaves `sending` permanently. Scan then overwrites the snapshot message (455–456) but does not repair `dispatch.json`.
- If `process_queue` successfully sends job A, then a later job raises before the final `write_json` (427), job A can remain `sending` on disk even after a successful paste (intermediate write at 387 already landed).

**Fix:** Allow `cancel` (and a distinct “abandon and allow retry”) for `sending` and `uncertain`. On cancel, do not remove `sent` unless the user opts into retry. On process start, treat leftover `sending` as `uncertain`. Catch the full `process_queue` loop and persist whatever was already decided. Optionally heartbeat/expire `sending`.

---

### 3. Transient discovery loss is treated as “project closed” and cancels the queue

**Severity:** High  
**Function:** `discover` (124–132, 125–126), `process_queue` (412–416), `scan` (431–438)  
**Reproduction:** Queue a dispatch while the agent is busy (`send_job` leaves `queued`). Next `scan`, make `session.snapshot` time out (12s) or fail, **or** have `herdr session list` omit `running`. That session’s workspaces disappear from `projects`. `process_queue` does not receive `errors`; missing key means cancelled: “Project closed; queued request cancelled.”

**Impact:** A timeout, brief Herdr restart, or `running: false` **permanently** drops queued work. User must notice and click again. Combined with finding 2, a job that had already recorded `sent` cannot be fully reconstructed.

**Fix:** Pass discovery errors into `process_queue`. If the session list itself failed, do not cancel. If a session/workspace is missing **and** that session had an RPC/`running` error, leave the job queued (or “waiting for Herdr”). Cancel only when the session list succeeded, the session is running, and that workspace id is truly gone.

---

### 4. One GitHub issues fetch failure aborts the whole dispatch/preview

**Severity:** Medium-high  
**Function:** `action` (494–495), `open_items` (200–215)  
**Reproduction:** Map several repos. Make `gh api --paginate` fail or return a non-list page for one of them (`Failure` at 207–208). `pool.map` raises; no job is written.

**Impact:** A single missing/private/rate-limited repo blocks every other repo’s items. Preview has the same all-or-nothing behavior. The user gets one error and an empty handoff.

**Fix:** Fetch per repo, collect successes, and attach per-repo errors (as `scan` already tries to do for counts). Dispatch the successful subset or refuse only if **all** fetches failed.

---

### 5. Project-level GitHub error is last-repo-wins and still sums stale counts

**Severity:** Medium  
**Function:** `scan` (442–453), `refresh_repos` (186–192)  
**Reproduction:** Project with two repos. First cached row has `error`; second is clean (or the reverse). On GraphQL failure, `{**old, "attempt", "error"}` keeps old `pullRequests`/`issues`.

**Impact:** `p["error"]` is overwritten each repo. An earlier failure is hidden if a later repo succeeds; a later failure paints the whole project even when other counts are good. Failed refresh still adds stale `totalCount`s, so the UI can show another account’s or last hour’s numbers next to an error.

**Fix:** Aggregate errors (list or first+count). On `error`, do not add counts (or flag them stale). Do not clear `p["error"]` on a later success unless every repo in the project succeeded.

---

### 6. `dispatch.lock` is held across slow GitHub I/O, so the queue cannot drain

**Severity:** Medium  
**Function:** `action` (478–514), `refresh_repos`, `open_items`  
**Reproduction:** Start `preview` or `dispatch` on a project with many repos (paginate timeout 120s, 4 workers). Concurrently run `scan` (which calls `process_queue` under the same lock) or another `dispatch`/`cancel`.

**Impact:** Not a nested deadlock: `scan` takes `github.lock` then releases it before `dispatch.lock`; `action` nests `dispatch.lock` → `github.lock`. It **is** a long exclusive section. Queued jobs for **every** project wait on someone else’s issue list. `cancel` waits too. Scan/UI refresh blocks. Preview does not even mutate the ledger.

**Fix:** Hold `dispatch.lock` only for read-modify-write of `dispatch.json`. Fetch issues and `refresh_repos` outside it; re-check version tokens after re-acquiring. Give preview its own path with no dispatch lock.

---

### 7. Draft PRs are treated as normal work

**Severity:** Medium  
**Function:** `open_items` (209–214), `brief_text` step 4 (252–253)  
**Reproduction:** Dispatch a repo that has an open draft PR. The list endpoint is `GET repos/.../issues`, which includes PRs via `pull_request` but does not populate PR `draft`. `row.get("draft", False)` is almost always `False`.

**Impact:** The brief says drafts are review-only unless the user asks to complete them. The agent is told they are ordinary PRs and may implement/push.

**Fix:** Detect PRs and fetch `draft` from the pull-request API or GraphQL (`isDraft`). Until then, mark unknown drafts explicitly rather than `False`.

---

### 8. `cancel` lies for any non-queued job

**Severity:** Medium  
**Function:** `action` cancel (481–485)  
**Reproduction:** Dispatch until status is `sent`/`rejected`/`uncertain`/`sending`. Run `cancel` on that key.

**Impact:** Status is unchanged. The message returned is the **old** job message (e.g. “Sent N items…”), which reads as if cancel succeeded. `sending`/`uncertain` still cannot be cleared (finding 2).

**Fix:** If status is not `queued`, return a distinct error: not queued, not cancelled. Optionally support cancelling the other terminal states.

---

### 9. `focus` RPC failure aborts dispatch after the GitHub work is done

**Severity:** Medium  
**Function:** `focus_project` (341–346), `action` (499–501)  
**Reproduction:** Valid agent and items; make `agent.focus` / `workspace.focus` raise `Failure`. Happens **after** `open_items`, **before** job creation.

**Impact:** `focus_window` (Hyprland) degrades to a warning string; Herdr focus does not. The user pays the full GitHub fetch cost and gets no queued job. Pending-job short-circuit (491–493) also throws instead of returning the pending message.

**Fix:** Treat Herdr focus like `focus_window`: warn, still queue/send. Focus is not required for `agent.prompt`.

---

### 10. `discover` only isolates `Failure` and `OSError` per session

**Severity:** Medium  
**Function:** `rpc` (79–84), `discover` (128–132), `project_key` (116–117)  
**Reproduction:** Herdr returns a non-JSON line, a JSON body without `result`, `error` as a string, or numeric `workspace_id`. `json.loads` → `JSONDecodeError`; `data["result"]` → `KeyError`; `data["error"].get` → `AttributeError`; `sock + "\0" + wid` → `TypeError`.

**Impact:** Those exceptions are **not** caught in the per-session `except`. The whole `discover`/`scan` dies. `main` catches `ValueError` and `KeyError` (JSON error payload) but **not** `TypeError`/`AttributeError` (traceback instead of `{"error": ...}`). A single bad session also prevents `process_queue` from running at all (unlike finding 3, which cancels when discovery *partially* succeeds).

**Fix:** Catch `Exception` (or at least `ValueError`, `KeyError`, `TypeError`, `AttributeError`) per session, record in `errors`, continue. Coerce `workspace_id` with `str()`. In `rpc`, require a dict `error` object; missing `result` should be `Failure`. In `main`, catch `TypeError`/`AttributeError` too.

---

### 11. Dispatch ledger and briefs grow without bound

**Severity:** Low-medium  
**Function:** `send_job` (385–386), `process_queue` (409–427), `action` (503–511)  
**Reproduction:** Use the tool over many days. Inspect `dispatch.json` and `STATE/briefs/`.

**Impact:** `ledger["sent"]` is never pruned. Terminal jobs (`sent`/`cancelled`/`skipped`/`rejected`) stay in `ledger["jobs"]` forever. Brief files are never deleted. Disk grows; skip-logic stays tied to ancient URL+`updated_at` keys with no operator control besides editing state.

**Fix:** TTL the `sent` map (e.g. align with 24h, or until the issue is closed). Remove or archive terminal jobs after scan has reported them. Delete brief files when the job is terminal.

---

### 12. `map` without `--path` maps the current working directory

**Severity:** Low  
**Function:** `action` map (469–477), `main` (523)  
**Reproduction:** `pr-hunter map --key …` with no `--path`, from a GitHub checkout.

**Impact:** `Path(path or "").expanduser().resolve()` is cwd. If cwd has a GitHub remote, the mapping is saved with no extra confirmation.

**Fix:** Require `--path` for `map`. Refuse empty/`None`.

---

## Protocol-dependent risks (not proven from this file alone)

These are real failure modes if Herdr/GitHub/hyprctl behave as many JSON APIs do. They are not fully confirmed without those schemas.

### A. `--pane` is a string; `pane_id` may not be

**Where:** `choose_agent` (359–360), `action` focus (467)  
CLI `--pane` is always `str`. If snapshot/`agent.list` uses numeric ids, `a["pane_id"] == pane` never matches. Focus silently focuses the workspace; dispatch reports “No supported local agent” even when agents exist.  
**Harden:** Compare as `str(a["pane_id"]) == str(pane)` and include that in `agent_identity`.

### B. Snapshot agents vs `agent.list` identity

**Where:** `discover` stores snapshot agents; `send_job` matches `agent.list` with dict equality on `pane_id`, `terminal_id`, `agent`, `agent_session`.  
Missing vs `null`, extra identity churn, or `agent_session` rotating on reconnect cancels with “Agent changed or exited” even though the same pane is idle. Too-loose identity (reused `pane_id` + same agent name) can send to a new occupant.  
**Harden:** Document the identity tuple; treat `agent_session` change as “ask again”; never match on pane id alone.

### C. `rpc` reads one line and requires the same `id`

Notifications, logs, or a banner before the response look like “Mismatched Herdr response” or “Incomplete Herdr response”. `error: {}` is falsy, so a rejected call can proceed to `data["result"]`.  
**Harden:** Read until the matching `id`; treat any present `error` key as rejection.

### D. Ready states `idle` / `done`

Unknown statuses stay queued forever (until 24h). If `done` is not promptable, a prompt is sent anyway. Status can change between the check and `agent.prompt` (double prompt or `Rejected` rollback).  
**Harden:** Explicit allow-list from Herdr; on unknown status, fail visibly; consider a single “submit if idle” RPC.

### E. `project_key(socket_path, workspace_id)` reuse

Socket path or recycled `workspace_id` changes the key (orphan/cancel, finding 3) or reuses it (queue delivered to a different workspace with the same repos/paths). Matching `project_repos` / `project_paths` is only a partial guard.  
**Harden:** Include a stable session id and a generation/boot id in the key.

### F. `window_candidates` process matching

Herdr argv shapes other than `--session` / `session attach` are ignored or treated as session `default`. PID reuse while walking `/proc` can focus the wrong window. Failure here is already a warning, not a failed send.

### G. GitHub GraphQL/`gh` shape

`p.returncode` is ignored in `refresh_repos` (unlike `run()`). Partial HTTP errors can mark a whole batch failed or parse oddly. `GET /issues` pagination can skip/duplicate items if the list changes mid-page. Untrusted titles/bodies in the brief are labeled untrusted; residual prompt injection remains an agent-side risk.

---

## What looks solid

- Argv subprocesses (no shell interpolation); repo names gated by `REPO` before `gh api`.
- Atomic `write_json` (unique tmp, `fsync`, `replace`).
- Advisory locks per file; dispatch read-modify-write is serialized.
- Dedup records `sent` before paste, rolls back only on definite `Rejected`.
- Brief tells the agent to re-fetch and skip closed items.
- `focus_address` validates Hyprland addresses before interpolation.
- Mapped config writes use `config.lock`; `write_json` replace makes unlocked `read_json` of config safe.

---

## Release order

Fix 1–3 before public release (wrong account, stuck queue, cancelled work on blips). Then 4–9 (partial GitHub failure, lock scope, drafts, cancel/focus/discovery error handling). Treat A–E as must-harden if pane ids are numeric or Herdr emits non-result lines.