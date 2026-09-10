import copy
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
        h.write_json(h.STATE / 'github.json', {'login': 'me', 'repos': {'me/repo': {
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
            self.assertIn('No new', result['message'])
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
