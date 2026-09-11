import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_hunter as h


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = patch.object(h, 'STATE', Path(self.tmp.name))
        self.state.start()
        self.config = patch.object(h, 'CONFIG', Path(self.tmp.name) / 'config.json')
        self.config.start()
        self.agent = {'pane_id': 'w1:p1', 'terminal_id': 'term1', 'agent': 'claude',
                      'agent_status': 'idle', 'agent_session': {'value': 'abc'}}
        self.item = {'url': 'https://github.com/me/repo/issues/1', 'updated': '2026-01-01',
                     'repo': 'me/repo', 'kind': 'Issue', 'number': 1, 'title': 'Fix it', 'draft': False}
        self.project = {'key': 'key', 'label': 'Test', 'session': 'default', 'workspace_id': 'w1',
                        'socket': '/test.sock', 'agents': [self.agent], 'repos': [
                            {'name': 'me/repo', 'roots': ['/test'], 'remotes': ['origin']}], 'mapping_key': 'default:Test'}
        self.job = {'id': 'job', 'identity': h.agent_identity(self.agent), 'items': [self.item],
                    'brief': '/private/brief.md', 'status': 'queued', 'created': h.time.time(),
                    'project_repos': ['me/repo']}
        self.ledger = {'sent': {}, 'jobs': {'key': self.job}}

    def tearDown(self):
        self.config.stop()
        self.state.stop()
        self.tmp.cleanup()

    def test_remote_parsing_rejects_credentials_and_non_github(self):
        for url in ['https://github.com/me/repo.git', 'git@github.com:me/repo.git', 'ssh://git@github.com/me/repo']:
            self.assertEqual(h.github_repo(url), 'me/repo')
        for url in ['https://evil.test/me/repo', 'https://secret@github.com/me/repo', 'https://github.com/me/repo/extra', 'DISABLED']:
            self.assertIsNone(h.github_repo(url))

    def test_rest_pagination_and_pr_classification(self):
        rows = [[{'number': 1, 'title': 'one', 'html_url': 'url1', 'updated_at': 'a'}],
                [{'number': 2, 'title': 'two', 'html_url': 'url2', 'updated_at': 'b', 'pull_request': {'url': 'x'}, 'draft': True}]]
        with patch.object(h, 'run', return_value=json.dumps(rows)) as run:
            result = h.open_items('me/repo')
        self.assertEqual([i['kind'] for i in result], ['Issue', 'PR'])
        self.assertTrue(result[1]['draft'])
        self.assertIn('--paginate', run.call_args.args[0])

    def test_busy_and_blocked_agents_never_receive_input(self):
        for status in ['working', 'blocked', 'unknown']:
            agent = {**self.agent, 'agent_status': status}
            with patch.object(h, 'rpc', return_value={'agents': [agent]}) as rpc:
                h.send_job(self.project, self.job, self.ledger)
            self.assertEqual(self.job['status'], 'queued')
            self.assertEqual(rpc.call_count, 1)
            self.assertEqual(self.ledger['sent'], {})

    def test_replaced_agent_cancels_queue(self):
        replacement = {**self.agent, 'terminal_id': 'different'}
        with patch.object(h, 'rpc', return_value={'agents': [replacement]}) as rpc:
            h.send_job(self.project, self.job, self.ledger)
        self.assertEqual(self.job['status'], 'cancelled')
        self.assertEqual(rpc.call_count, 1)

    def test_queue_skips_items_sent_from_another_worktree(self):
        self.ledger['sent'][h.version(self.item)] = {'job': 'another-project'}
        with patch.object(h, 'rpc') as rpc:
            h.send_job(self.project, self.job, self.ledger)
        self.assertEqual(self.job['status'], 'skipped')
        rpc.assert_not_called()

    def test_queue_cancels_on_checkout_change_with_same_remote(self):
        self.job['project_paths'] = ['/old/checkout']
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        project = {**self.project, 'paths': ['/new/checkout']}
        with patch.object(h, 'send_job') as send:
            result = h.process_queue([project])
        self.assertEqual(result['jobs']['key']['status'], 'cancelled')
        send.assert_not_called()

    def test_receipt_written_before_send(self):
        def rpc(sock, method, params=None):
            if method == 'agent.list':
                return {'agents': [self.agent]}
            saved = h.read_json(h.STATE / 'dispatch.json')
            self.assertIn(h.version(self.item), saved['sent'])
            self.assertEqual(params['target'], 'w1:p1')
            self.assertIn('/private/brief.md', params['text'])
            return {'type': 'ok'}
        with patch.object(h, 'rpc', side_effect=rpc):
            h.send_job(self.project, self.job, self.ledger)
        self.assertEqual(self.job['status'], 'sent')

    def test_ambiguous_transport_does_not_allow_duplicate_send(self):
        with patch.object(h, 'rpc', side_effect=[{'agents': [self.agent]}, TimeoutError('late')]):
            h.send_job(self.project, self.job, self.ledger)
        self.assertEqual(self.job['status'], 'uncertain')
        self.assertIn(h.version(self.item), self.ledger['sent'])

    def test_definite_rejection_releases_receipt(self):
        with patch.object(h, 'rpc', side_effect=[{'agents': [self.agent]}, h.Rejected('blocked')]):
            h.send_job(self.project, self.job, self.ledger)
        self.assertEqual(self.job['status'], 'rejected')
        self.assertNotIn(h.version(self.item), self.ledger['sent'])

    def test_changed_mapping_cancels_queue(self):
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        project = {**self.project, 'repos': [{'name': 'me/other'}]}
        with patch.object(h, 'send_job') as send:
            result = h.process_queue([project])
        self.assertEqual(result['jobs']['key']['status'], 'cancelled')
        send.assert_not_called()

    def test_closed_project_and_expired_request_cancel(self):
        for projects, age in [([], 0), ([self.project], 90000)]:
            ledger = copy.deepcopy(self.ledger)
            ledger['jobs']['key']['created'] = h.time.time() - age
            h.write_json(h.STATE / 'dispatch.json', ledger)
            with patch.object(h, 'send_job') as send:
                result = h.process_queue(projects)
            self.assertEqual(result['jobs']['key']['status'], 'cancelled')
            send.assert_not_called()

    def test_multiple_agents_require_explicit_target(self):
        self.project['agents'].append({**self.agent, 'pane_id': 'w1:p2'})
        with self.assertRaises(h.Failure):
            h.choose_agent(self.project)
        self.assertEqual(h.choose_agent(self.project, 'w1:p2')['pane_id'], 'w1:p2')

    def test_scope_and_untrusted_brief(self):
        self.project['repos'].append({'name': 'up/repo', 'roots': ['/test'], 'remotes': ['upstream']})
        self.assertEqual([r['name'] for r in h.select_repos(self.project, 'mine', 'me')], ['me/repo'])
        self.assertEqual([r['name'] for r in h.select_repos(self.project, 'upstream', 'me')], ['up/repo'])
        brief = h.brief_text(self.project, self.project['repos'], [self.item])
        for text in ['untrusted GitHub data', 'CI', 'comments', 'commit', 'does not authorize', self.item['url']]:
            self.assertIn(text, brief)

    def test_only_exact_client_ancestry_is_focused(self):
        clients = [{'pid': 10, 'address': 'right', 'mapped': True}, {'pid': 30, 'address': 'wrong', 'mapped': True}]
        processes = {10: {'ppid': 1, 'name': 'foot', 'args': ['foot']},
                     11: {'ppid': 10, 'name': 'herdr', 'args': ['herdr', '--session', 'work']},
                     31: {'ppid': 30, 'name': 'herdr', 'args': ['herdr', 'agent', 'list']}}
        self.assertEqual(h.window_candidates('work', clients, processes)[0]['address'], 'right')
        self.assertEqual(h.window_candidates('default', clients, processes), [])

    def test_focus_supports_lua_and_legacy_hyprland(self):
        for tag, expected in [('v0.56.0', 'hl.dsp.focus'), ('v0.54.0', 'focuswindow')]:
            with patch.object(h, 'run', side_effect=[json.dumps({'tag': tag}), 'ok']) as run:
                h.focus_address('0x123abc')
            self.assertIn(expected, run.call_args.args[0][2])
        with self.assertRaises(h.Failure):
            h.focus_address('0x123"; malicious()')

    def test_partial_github_error_retains_previous_count(self):
        h.write_json(h.STATE / 'github.json', {'login': 'me', 'login_checked': h.time.time(), 'repos': {'me/repo': {
            'checked': 1, 'attempt': 1, 'pullRequests': {'totalCount': 9}}}})
        fake = type('Process', (), {'stdout': json.dumps({'data': {'r0': None}, 'errors': [{'path': ['r0'], 'message': 'not found'}]}), 'stderr': '', 'returncode': 1})()
        with patch.object(h.subprocess, 'run', return_value=fake):
            result = h.refresh_repos(['me/repo'])
        self.assertEqual(result['repos']['me/repo']['pullRequests']['totalCount'], 9)
        self.assertEqual(result['repos']['me/repo']['error'], 'not found')

    def test_dispatch_deduplicates_item_versions(self):
        self.ledger['sent'][h.version(self.item)] = {'job': 'old'}
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        with patch.object(h, 'find_project', return_value=self.project), \
             patch.object(h, 'refresh_repos', return_value={'login': 'me'}), \
             patch.object(h, 'open_items', return_value=[self.item]), \
             patch.object(h, 'focus_project', return_value=''), \
             patch.object(h, 'send_job') as send:
            # Existing queued jobs also prevent another submission.
            h.action('key', 'dispatch')
            send.assert_not_called()
            self.ledger['jobs'] = {}
            h.write_json(h.STATE / 'dispatch.json', self.ledger)
            result = h.action('key', 'dispatch')
            self.assertIn('Nothing new to send', result['message'])
            self.assertIn('Send again', result['message'])
            send.assert_not_called()

    def test_incomplete_discovery_preserves_queued_handoff(self):
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        with patch.object(h, 'send_job') as send:
            result = h.process_queue([], discovery_incomplete=True)
        self.assertEqual(result['jobs']['key']['status'], 'queued')
        self.assertIn('complete Herdr scan', result['jobs']['key']['message'])
        send.assert_not_called()

    def test_git_timeout_only_omits_affected_project(self):
        session = {'name': 'default', 'socket_path': '/test.sock', 'running': True}
        snap = {'workspaces': [{'workspace_id': 'w1', 'label': 'slow'}, {'workspace_id': 'w2', 'label': 'good'}],
                'panes': [], 'agents': []}
        with patch.object(h, 'run', return_value=json.dumps({'sessions': [session]})), \
             patch.object(h, 'rpc', return_value={'snapshot': snap}), \
             patch.object(h, 'workspace_project', side_effect=[h.subprocess.TimeoutExpired(['git'], 5), self.project]):
            projects, errors = h.discover()
        self.assertEqual(projects, [self.project])
        self.assertEqual(len(errors), 1)

    def test_preview_does_not_require_agent_or_focus(self):
        project = {**self.project, 'agents': []}
        with patch.object(h, 'find_project', return_value=project), \
             patch.object(h, 'refresh_repos', return_value={'login': 'me'}), \
             patch.object(h, 'open_items', return_value=[self.item]), \
             patch.object(h, 'focus_project') as focus:
            result = h.action('key', 'preview')
        self.assertEqual(result['items'], [self.item])
        focus.assert_not_called()

    def test_focus_unmapped_workspace_without_agent(self):
        project = {**self.project, 'agents': [], 'repos': []}
        with patch.object(h, 'find_project', return_value=project), \
             patch.object(h, 'focus_project', return_value='') as focus, \
             patch.object(h, 'refresh_repos') as github:
            h.action('key', 'focus')
        focus.assert_called_once_with(project, None)
        github.assert_not_called()

    def test_dispatch_joins_session_even_when_github_fails(self):
        with patch.object(h, 'find_project', return_value=self.project), \
             patch.object(h, 'refresh_repos', side_effect=h.Failure('offline')), \
             patch.object(h, 'focus_project', return_value='') as focus:
            with self.assertRaisesRegex(h.Failure, 'offline'):
                h.action('key', 'dispatch')
        focus.assert_called_once_with(self.project, self.agent)

    def test_dispatch_rechecks_mapping_after_network_fetch(self):
        changed = copy.deepcopy(self.project)
        changed['repos'][0]['roots'] = ['/changed']
        with patch.object(h, 'find_project', side_effect=[self.project, changed]), \
             patch.object(h, 'refresh_repos', return_value={'login': 'me'}), \
             patch.object(h, 'open_items', return_value=[self.item]), \
             patch.object(h, 'focus_project', return_value=''), \
             patch.object(h, 'send_job') as send:
            with self.assertRaisesRegex(h.Failure, 'mapping changed'):
                h.action('key', 'dispatch')
        send.assert_not_called()

    def test_dispatch_rechecks_agent_after_network_fetch(self):
        changed = copy.deepcopy(self.project)
        changed['agents'][0]['terminal_id'] = 'replacement'
        with patch.object(h, 'find_project', side_effect=[self.project, changed]), \
             patch.object(h, 'refresh_repos', return_value={'login': 'me'}), \
             patch.object(h, 'open_items', return_value=[self.item]), \
             patch.object(h, 'focus_project', return_value=''), \
             patch.object(h, 'send_job') as send:
            with self.assertRaisesRegex(h.Failure, 'Agent changed'):
                h.action('key', 'dispatch')
        send.assert_not_called()

    def test_pending_job_is_persisted_before_transport_check(self):
        def unavailable(*args):
            saved = h.read_json(h.STATE / 'dispatch.json')
            self.assertEqual(saved['jobs']['key']['status'], 'queued')
            raise h.Failure('offline')
        with patch.object(h, 'find_project', return_value=self.project), \
             patch.object(h, 'refresh_repos', return_value={'login': 'me'}), \
             patch.object(h, 'open_items', return_value=[self.item]), \
             patch.object(h, 'focus_project', return_value=''), \
             patch.object(h, 'send_job', side_effect=unavailable):
            with self.assertRaisesRegex(h.Failure, 'offline'):
                h.action('key', 'dispatch')
        self.assertEqual(h.read_json(h.STATE / 'dispatch.json')['jobs']['key']['status'], 'queued')

    def test_account_switch_invalidates_other_accounts_cache(self):
        h.write_json(h.STATE / 'github.json', {'login': 'old', 'login_checked': h.time.time(),
                     'repos': {'old/private': {'pullRequests': {'totalCount': 42}}}})
        with patch.object(h, 'run', return_value='new'):
            cache = h.refresh_repos([], check_account=True)
        self.assertEqual(cache['login'], 'new')
        self.assertEqual(cache['repos'], {})

    def test_queue_validates_roots_and_remotes(self):
        self.job['project_signature'] = h.project_signature(self.project)
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        project = copy.deepcopy(self.project)
        project['repos'][0]['remotes'] = ['upstream']
        with patch.object(h, 'send_job') as send:
            result = h.process_queue([project])
        self.assertEqual(result['jobs']['key']['status'], 'cancelled')
        send.assert_not_called()

    def test_private_brief_is_atomic_and_owner_only(self):
        path = h.STATE / 'briefs' / 'private.md'
        h.write_private(path, 'a private brief')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.read_text(), 'a private brief')
        h.write_private(path, 'replacement')
        self.assertEqual(path.read_text(), 'replacement')
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_interrupted_send_becomes_uncertain_and_can_be_acknowledged(self):
        self.job['status'] = 'sending'
        self.ledger['sent'][h.version(self.item)] = {'job': 'job'}
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        result = h.process_queue([self.project])
        self.assertEqual(result['jobs']['key']['status'], 'uncertain')
        with patch.object(h, 'find_project', return_value=self.project):
            result = h.action('key', 'acknowledge')
        self.assertIn('remain protected', result['message'])
        saved = h.read_json(h.STATE / 'dispatch.json')
        self.assertEqual(saved['jobs']['key']['status'], 'acknowledged')
        self.assertIn(h.version(self.item), saved['sent'])

    def test_cancel_nonqueued_does_not_report_old_success(self):
        self.job.update(status='sent', message='Sent 1 item')
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        with patch.object(h, 'find_project', return_value=self.project):
            result = h.action('key', 'cancel')
        self.assertIn('Nothing was changed', result['message'])
        self.assertEqual(h.read_json(h.STATE / 'dispatch.json')['jobs']['key']['status'], 'sent')

    def test_partial_fetch_preserves_available_items_and_reports_gap(self):
        repos = [{'name': 'me/good'}, {'name': 'me/unavailable'}]
        def get(name):
            if name.endswith('unavailable'):
                raise h.Failure('offline')
            return [self.item]
        with patch.object(h, 'open_items', side_effect=get):
            items, errors = h.fetch_items(repos)
        self.assertEqual(items, [self.item])
        self.assertEqual(errors, ['me/unavailable: offline'])
        self.assertIn('No items from them were assigned', h.unavailable_text(errors))

    def test_map_requires_path(self):
        with patch.object(h, 'find_project', return_value=self.project), patch.object(h, 'git_repos') as git:
            with self.assertRaisesRegex(h.Failure, 'path is required'):
                h.action('key', 'map')
        git.assert_not_called()

    def test_stopped_session_is_incomplete_discovery(self):
        with patch.object(h, 'run', return_value=json.dumps({'sessions': [{'name': 'default', 'running': False}]})):
            projects, errors = h.discover()
        self.assertEqual(projects, [])
        self.assertIn('paused', errors[0])

    def test_named_session_with_equals_matches_exact_terminal(self):
        clients = [{'pid': 10, 'address': 'right', 'mapped': True}]
        processes = {10: {'ppid': 1, 'name': 'foot', 'args': ['foot']},
                     11: {'ppid': 10, 'name': 'herdr', 'args': ['herdr', '--session=work']}}
        self.assertEqual(h.window_candidates('work', clients, processes)[0]['address'], 'right')
        self.assertEqual(h.window_candidates('default', clients, processes), [])

    def test_unattached_session_launches_only_existing_session_client(self):
        with patch.object(h, 'run', return_value='[]'), \
             patch.object(h.Path, 'glob', return_value=[]), \
             patch.object(h.subprocess, 'Popen') as spawn:
            spawn.return_value.wait.return_value = 0
            result = h.focus_window('work')
        self.assertEqual(spawn.call_args.args[0], ['xdg-terminal-exec', '--', 'herdr', 'session', 'attach', 'work'])
        self.assertIn('existing Herdr session', result)

    def test_missing_draft_state_is_unknown_not_false(self):
        row = {'number': 1, 'title': 'PR', 'html_url': 'url', 'updated_at': 'now', 'pull_request': {'url': 'api'}}
        with patch.object(h, 'run', return_value=json.dumps([[row]])):
            self.assertIsNone(h.open_items('me/repo')[0]['draft'])

    def test_rpc_only_known_preinput_prompt_rejection_is_definite(self):
        for code, expected in [('agent_blocked', h.Rejected), ('internal_error', h.Failure)]:
            request = {}
            with patch.object(h.socket, 'socket') as factory:
                conn = factory.return_value.__enter__.return_value
                conn.sendall.side_effect = lambda raw: request.update(json.loads(raw))
                conn.makefile.side_effect = lambda mode: io.BytesIO((json.dumps({
                    'id': request['id'], 'error': {'code': code, 'message': 'failed'}}) + '\n').encode())
                with self.assertRaises(expected) as caught:
                    h.rpc('/test', 'agent.prompt', {'target': 'w1:p1', 'text': 'test'})
                if code == 'internal_error':
                    self.assertNotIsInstance(caught.exception, h.Rejected)

    def test_malformed_snapshot_does_not_hide_healthy_session(self):
        sessions = [{'name': 'bad', 'running': True, 'socket_path': '/bad'},
                    {'name': 'good', 'running': True, 'socket_path': '/good'}]
        good = {'workspaces': [{'workspace_id': 'w1', 'label': 'good'}], 'panes': [], 'agents': []}
        with patch.object(h, 'run', return_value=json.dumps({'sessions': sessions})), \
             patch.object(h, 'rpc', side_effect=[{'snapshot': {}}, {'snapshot': good}]):
            projects, errors = h.discover()
        self.assertEqual([p['label'] for p in projects], ['good'])
        self.assertEqual(len(errors), 1)

    def test_scan_ranks_busiest_project_and_repo_first(self):
        def project(key, label, repos):
            return {'key': key, 'label': label, 'session': 's', 'repos': repos,
                    'agents': [], 'paths': ['/p'], 'open': True}

        def repo(name, prs, issues):
            return {'name': name, 'roots': ['/p'], 'remotes': []}

        projects = [project('quiet', 'quiet', [repo('me/quiet', 0, 0)]),
                    project('busy', 'busy', [repo('me/small', 0, 0), repo('me/large', 0, 0)])]
        cache = {'login': 'me', 'repos': {
            'me/quiet': {'pullRequests': {'totalCount': 0}, 'issues': {'totalCount': 0}, 'checked': 1},
            'me/small': {'pullRequests': {'totalCount': 1}, 'issues': {'totalCount': 0}, 'checked': 1},
            'me/large': {'pullRequests': {'totalCount': 2}, 'issues': {'totalCount': 5}, 'checked': 1}}}
        with patch.object(h, 'discover', return_value=(projects, [])), \
             patch.object(h, 'process_queue', return_value={'jobs': {}}), \
             patch.object(h, 'refresh_repos', return_value=cache):
            result = h.scan()
        self.assertEqual([p['label'] for p in result['projects']], ['busy', 'quiet'])
        busy = result['projects'][0]
        self.assertEqual([r['name'] for r in busy['repos']], ['me/large', 'me/small'])
        self.assertEqual(busy['pr_count'] + busy['issue_count'], 8)
        self.assertEqual(result['projects'][1]['pr_count'] + result['projects'][1]['issue_count'], 0)

    def test_send_again_releases_only_this_project_receipts(self):
        self.ledger['sent'] = {h.version(self.item): {'job': 'old'}, 'other/repo#9@x': {'job': 'old'}}
        self.ledger['jobs'] = {}
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        with patch.object(h, 'find_project', return_value=self.project), \
             patch.object(h, 'refresh_repos', return_value={'login': 'me'}), \
             patch.object(h, 'open_items', return_value=[self.item]), \
             patch.object(h, 'focus_project', return_value=''), \
             patch.object(h, 'send_job') as send:
            h.action('key', 'dispatch', force=True)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1]['items'], [self.item])
        self.assertIn('other/repo#9@x', h.read_json(h.STATE / 'dispatch.json')['sent'])

    def test_empty_scope_names_the_scope_holding_the_work(self):
        project = {**self.project, 'repos': [
            {'name': 'me/fork', 'roots': ['/test'], 'remotes': ['origin']},
            {'name': 'them/upstream', 'roots': ['/test'], 'remotes': ['upstream']}]}
        cache = {'login': 'me', 'repos': {
            'me/fork': {'pullRequests': {'totalCount': 0}, 'issues': {'totalCount': 0}},
            'them/upstream': {'pullRequests': {'totalCount': 28}, 'issues': {'totalCount': 68}}}}
        self.ledger['jobs'] = {}
        h.write_json(h.STATE / 'dispatch.json', self.ledger)
        with patch.object(h, 'find_project', return_value=project), \
             patch.object(h, 'refresh_repos', return_value=cache), \
             patch.object(h, 'open_items', return_value=[]), \
             patch.object(h, 'focus_project', return_value=''), \
             patch.object(h, 'send_job') as send:
            result = h.action('key', 'dispatch', 'mine')
        send.assert_not_called()
        self.assertIn('96 open items', result['message'])
        self.assertIn('upstream', result['message'])

    def test_focus_explains_why_no_work_was_sent(self):
        cases = [({'agents': []}, 'No local agent is running'),
                 ({'repos': []}, 'No GitHub repository is mapped'),
                 ({'agents': [self.agent, {**self.agent, 'pane_id': 'w1:p2'}]}, 'Several agents')]
        for override, expected in cases:
            with patch.object(h, 'find_project', return_value={**self.project, **override}), \
                 patch.object(h, 'focus_project', return_value=''):
                result = h.action('key', 'focus')
            self.assertIn(expected, result['message'])

    def test_every_action_is_logged_for_diagnosis(self):
        args = type('Args', (), {'command': 'dispatch', 'key': 'key', 'scope': 'mine',
                                 'pane': 'w1:p1', 'force': False})()
        h.log_action(args, h.time.time(), result={'message': 'Sent 3 items', 'status': 'sent'})
        h.log_action(args, h.time.time(), error='Agent changed while preparing work')
        rows = [json.loads(l) for l in (h.STATE / 'actions.log').read_text().splitlines()]
        self.assertEqual([r['message'] for r in rows], ['Sent 3 items', None])
        self.assertEqual(rows[1]['error'], 'Agent changed while preparing work')
        self.assertEqual(rows[0]['scope'], 'mine')

    def test_checkout_suggestion_only_offers_a_real_repository(self):
        home = Path(self.tmp.name)
        good = home / 'Projects' / 'site.example.com'
        good.mkdir(parents=True)
        with patch.object(h.Path, 'home', staticmethod(lambda: home)), \
             patch.object(h, 'git_repos', side_effect=lambda path: [{'name': 'me/site'}] if path == str(good) else []):
            self.assertEqual(h.suggest_checkout({'label': 'site.example.com', 'paths': [str(home)]}), str(good))
            self.assertEqual(h.suggest_checkout({'label': 'Now Playing', 'paths': [str(home)]}), '')
            self.assertEqual(h.suggest_checkout({'label': '../etc', 'paths': [str(home)]}), '')

    def test_delivered_work_stops_holding_the_top_of_the_list(self):
        def project(key, label, repo):
            return {'key': key, 'label': label, 'session': 's', 'agents': [], 'paths': ['/p'],
                    'open': True, 'repos': [{'name': repo, 'roots': ['/p'], 'remotes': []}]}

        projects = [project('done', 'handed off', 'me/done'), project('fresh', 'untouched', 'me/fresh')]
        cache = {'login': 'me', 'repos': {
            'me/done': {'pullRequests': {'totalCount': 5}, 'issues': {'totalCount': 4}, 'checked': 1},
            'me/fresh': {'pullRequests': {'totalCount': 2}, 'issues': {'totalCount': 0}, 'checked': 1}}}
        ledger = {'jobs': {}, 'sent': {f'https://github.com/me/done/issues/{n}@t': {} for n in range(9)}}
        with patch.object(h, 'discover', return_value=(projects, [])), \
             patch.object(h, 'process_queue', return_value=ledger), \
             patch.object(h, 'refresh_repos', return_value=cache):
            result = h.scan()
        # Nine open items, all already with an agent, so two untouched ones outrank them.
        self.assertEqual([p['label'] for p in result['projects']], ['untouched', 'handed off'])
        handed = result['projects'][1]
        self.assertEqual((handed['pr_count'] + handed['issue_count'], handed['delivered_count'], handed['pending_count']), (9, 9, 0))
        self.assertEqual(result['projects'][0]['pending_count'], 2)

    def test_delivery_never_counts_more_than_is_open(self):
        projects = [{'key': 'k', 'label': 'shrunk', 'session': 's', 'agents': [], 'paths': ['/p'],
                     'open': True, 'repos': [{'name': 'Me/Repo', 'roots': ['/p'], 'remotes': []}]}]
        cache = {'login': 'me', 'repos': {'Me/Repo': {'pullRequests': {'totalCount': 1}, 'issues': {'totalCount': 0}, 'checked': 1}}}
        # Six were delivered; five have since been closed, and case must not matter.
        ledger = {'jobs': {}, 'sent': {f'https://github.com/me/repo/pull/{n}@t': {} for n in range(6)}}
        with patch.object(h, 'discover', return_value=(projects, [])), \
             patch.object(h, 'process_queue', return_value=ledger), \
             patch.object(h, 'refresh_repos', return_value=cache):
            result = h.scan()
        self.assertEqual(result['projects'][0]['delivered_count'], 1)
        self.assertEqual(result['projects'][0]['pending_count'], 0)


if __name__ == '__main__':
    unittest.main()
