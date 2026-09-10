import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pr_hunter as h


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / 'project with spaces $(literal)'
        self.directory.mkdir()
        self.state = patch.object(h, 'STATE', self.root / 'state')
        self.config = patch.object(h, 'CONFIG', self.root / 'config.json')
        self.state.start(); self.config.start()
        self.project = {'key': 'saved', 'label': 'Project', 'session': 'default',
                        'socket': '/socket', 'workspace_id': 'w1', 'mapping_key': 'default:Project',
                        'paths': [str(self.directory)], 'repos': [], 'agents': [], 'open': False}

    def tearDown(self):
        self.config.stop(); self.state.stop(); self.temp.cleanup()

    def remember(self):
        h.write_json(h.STATE / 'projects.json', {'projects': {'saved': h.saved_record(self.project)}})

    def test_missing_herdr_preserves_saved_projects(self):
        self.remember()
        with patch.object(h, 'run', side_effect=FileNotFoundError('herdr')), patch.object(h, 'git_repos', return_value=[]):
            projects, errors = h.discover()
        self.assertEqual(errors, [])
        self.assertEqual(projects[0]['paths'], [str(self.directory)])
        self.assertFalse(projects[0]['open'])
        self.assertEqual(projects[0]['agents'], [])

    def test_closed_then_recreated_workspace_keeps_saved_row_key(self):
        first = {**self.project, 'open': True, 'key': 'original'}
        with patch.object(h, 'discover_live', return_value=([first], [])):
            self.assertEqual(h.discover()[0][0]['key'], 'original')
        with patch.object(h, 'discover_live', return_value=([], [])), patch.object(h, 'git_repos', return_value=[]):
            self.assertFalse(h.discover()[0][0]['open'])
        recreated = {**first, 'key': 'new-id', 'workspace_id': 'w2'}
        with patch.object(h, 'discover_live', return_value=([recreated], [])):
            rows, _ = h.discover()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['key'], 'original')
        self.assertEqual(rows[0]['workspace_id'], 'w2')

    def test_upgrade_does_not_merge_distinct_workspaces_with_same_directory(self):
        one = {**self.project, 'key': 'one', 'open': True}
        two = {**self.project, 'key': 'two', 'workspace_id': 'w2', 'open': True}
        h.write_json(h.STATE / 'snapshot.json', {'projects': [one, two]})
        with patch.object(h, 'discover_live', return_value=([two, one], [])):
            rows, _ = h.discover()
        self.assertEqual({r['key']: r['workspace_id'] for r in rows}, {'one': 'w1', 'two': 'w2'})

    def test_add_project_without_herdr_persists_folder(self):
        with patch.object(h, 'discover_live', return_value=([], [])), patch.object(h, 'git_repos', return_value=[]):
            result = h.add_project(str(self.directory))
            rows, _ = h.discover()
            duplicate = h.add_project(str(self.directory))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['key'], result['key'])
        self.assertEqual(result['key'], duplicate['key'])
        self.assertEqual(h.CONFIG.stat().st_mode & 0o777, 0o600)

    def test_empty_or_missing_directory_is_not_replaced_with_home(self):
        for path in ['', str(self.root / 'missing')]:
            with self.assertRaises(h.Failure):
                h.add_project(path)
        self.project['paths'] = [str(self.root / 'missing')]
        with patch.object(h.subprocess, 'Popen') as spawn:
            with self.assertRaises(h.Failure): h.open_saved_project(self.project)
        spawn.assert_not_called()

    def test_no_herdr_opens_default_terminal_in_exact_directory(self):
        with patch.object(h.shutil, 'which', side_effect=lambda name: None if name == 'herdr' else '/usr/bin/' + name), \
             patch.object(h, 'run', side_effect=h.Failure('no compositor')), \
             patch.object(h.subprocess, 'Popen') as spawn, patch.object(h, 'rpc') as rpc:
            spawn.return_value.wait.return_value = 0
            result = h.open_saved_project(self.project)
        argv = spawn.call_args.args[0]
        self.assertEqual(argv[0], 'xdg-terminal-exec')
        self.assertIn('--dir=' + str(self.directory), argv)
        self.assertEqual(spawn.call_args.kwargs['cwd'], str(self.directory))
        self.assertNotIn('shell', spawn.call_args.kwargs)
        self.assertNotIn('herdr', argv)
        self.assertIn(str(self.directory), result)
        rpc.assert_not_called()

    def test_new_terminal_does_not_inherit_another_panes_context(self):
        with patch.dict(h.os.environ, {'HERDR_ENV': '1', 'HERDR_PANE_ID': 'w9:p1', 'HERDR_SOCKET_PATH': '/old',
                                       'HERDR_CONFIG_PATH': '/custom/config.toml', 'PATH': '/bin'}):
            env = h.launch_environment()
        self.assertNotIn('HERDR_PANE_ID', env)
        self.assertNotIn('HERDR_SOCKET_PATH', env)
        self.assertEqual(env['HERDR_CONFIG_PATH'], '/custom/config.toml')

    def test_herdr_reuses_matching_workspace_without_creating_or_prompting(self):
        live = {**self.project, 'open': True}
        with patch.object(h.shutil, 'which', return_value='/bin/tool'), \
             patch.object(h, 'ensure_herdr_session', return_value='/socket'), \
             patch.object(h, 'rpc', side_effect=[{'snapshot': {'workspaces': [{}]}}, {}]) as rpc, \
             patch.object(h, 'workspace_project', return_value=live), \
             patch.object(h, 'discover', return_value=([live], [])), \
             patch.object(h, 'focus_window', return_value=''):
            h.open_saved_project(self.project)
        self.assertEqual([c.args[1] for c in rpc.call_args_list], ['session.snapshot', 'workspace.focus'])

    def test_herdr_creates_workspace_with_explicit_cwd(self):
        with patch.object(h.shutil, 'which', return_value='/bin/tool'), \
             patch.object(h, 'ensure_herdr_session', return_value='/socket'), \
             patch.object(h, 'rpc', side_effect=[{'snapshot': {'workspaces': []}}, {}]) as rpc, \
             patch.object(h, 'discover', return_value=([], [])), \
             patch.object(h, 'focus_window', return_value=''):
            h.open_saved_project(self.project)
        self.assertEqual(rpc.call_args.args[1], 'workspace.create')
        self.assertEqual(rpc.call_args.args[2], {'cwd': str(self.directory), 'label': 'Project', 'focus': True})

    def test_herdr_start_failure_falls_back_to_plain_terminal(self):
        with patch.object(h.shutil, 'which', return_value='/bin/tool'), \
             patch.object(h, 'ensure_herdr_session', side_effect=h.Failure('startup failed')), \
             patch.object(h, 'open_terminal', return_value='Terminal opened') as terminal:
            result = h.open_saved_project(self.project)
        self.assertIn('Herdr unavailable', result)
        terminal.assert_called_once_with(self.project)

    def test_stopped_server_starts_only_requested_session_in_project_dir(self):
        responses = [json.dumps({'sessions': []}), json.dumps({'sessions': [
            {'name': 'chosen', 'running': True, 'socket_path': '/chosen'}]})]
        with patch.object(h, 'run', side_effect=responses), patch.object(h.subprocess, 'Popen') as spawn:
            sock = h.ensure_herdr_session('chosen', str(self.directory))
        self.assertEqual(sock, '/chosen')
        self.assertEqual(spawn.call_args.args[0], ['herdr', '--session', 'chosen', 'server'])
        self.assertEqual(spawn.call_args.kwargs['cwd'], str(self.directory))

    def test_old_queue_is_never_delivered_to_saved_project(self):
        job = {'id': 'old', 'created': h.time.time(), 'status': 'queued'}
        h.write_json(h.STATE / 'dispatch.json', {'sent': {}, 'jobs': {'saved': job}})
        with patch.object(h, 'send_job') as send:
            result = h.process_queue([self.project])
        self.assertEqual(result['jobs']['saved']['status'], 'cancelled')
        send.assert_not_called()

    def test_dispatch_closed_project_only_opens_it(self):
        with patch.object(h, 'find_project', return_value=self.project), \
             patch.object(h, 'open_saved_project', return_value='Opened') as opening, \
             patch.object(h, 'send_job') as send:
            result = h.action('saved', 'dispatch')
        opening.assert_called_once_with(self.project)
        send.assert_not_called()
        self.assertIn('Start or select an agent', result['message'])

    def test_terminal_match_requires_tag_and_foreground_directory(self):
        clients = [{'class': 'project-tag', 'pid': 10, 'mapped': True, 'address': 'correct'},
                   {'class': 'other', 'pid': 10, 'mapped': True, 'address': 'wrong'}]
        processes = {10: {'ppid': 1}, 11: {'ppid': 10, 'cwd': str(self.directory), 'pgrp': 11, 'tpgid': 11}}
        self.assertEqual(h.terminal_matches(str(self.directory), 'project-tag', clients, processes), [clients[0]])
        processes[11]['cwd'] = '/different/project'
        self.assertEqual(h.terminal_matches(str(self.directory), 'project-tag', clients, processes), [])

    def test_double_click_does_not_launch_two_terminals(self):
        with patch.object(h.shutil, 'which', return_value='/bin/terminal'), \
             patch.object(h, 'run', return_value='[]'), \
             patch.object(h, 'process_snapshot', return_value={}), \
             patch.object(h.subprocess, 'Popen') as spawn:
            spawn.return_value.wait.return_value = 0
            h.open_terminal(self.project)
            result = h.open_terminal(self.project)
        self.assertEqual(spawn.call_count, 1)
        self.assertIn('is opening', result)


if __name__ == '__main__':
    unittest.main()
