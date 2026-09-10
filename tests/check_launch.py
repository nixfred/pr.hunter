"""Native cold-start/reopen test and no-Herdr terminal argv/cwd receipt.

Uses isolated XDG/Herdr storage and a fake terminal launcher. No desktop windows
or production sessions are opened, and no prompt is submitted to an agent.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_hunter as h


def check():
    with tempfile.TemporaryDirectory(prefix='pr-hunter-launch-test-') as directory:
        temp = Path(directory)
        checkout = temp / 'project with spaces $(literal)'
        checkout.mkdir()
        cfg = temp / 'herdr.toml'
        cfg.write_text('onboarding = false\n[terminal]\ndefault_shell = "/bin/sh"\n'
                       '[update]\nversion_check = false\nmanifest_check = false\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}
        for name, folder in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                             ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache')]:
            env[name] = str(temp / folder)
        env['HERDR_CONFIG_PATH'] = str(cfg)
        shim = temp / 'bin'; shim.mkdir()
        receipt = temp / 'terminal.json'
        launcher = shim / 'xdg-terminal-exec'
        launcher.write_text('#!/usr/bin/python3\nimport json,os,sys\n'
                            'from pathlib import Path\n'
                            'Path(os.environ["PR_HUNTER_TEST_RECEIPT"]).write_text(json.dumps({"cwd":os.getcwd(),"argv":sys.argv[1:]}))\n')
        launcher.chmod(0o700)
        env['PATH'] = str(shim) + os.pathsep + os.environ['PATH']
        env['PR_HUNTER_TEST_RECEIPT'] = str(receipt)
        spawned = []
        original_popen = subprocess.Popen
        def popen(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            if args[0][:1] == ['herdr'] and 'server' in args[0]:
                spawned.append(child)
            return child
        try:
            with patch.dict(os.environ, env, clear=True), patch.object(h, 'STATE', temp / 'hunter-state'), \
                 patch.object(h, 'CONFIG', temp / 'hunter-config.json'), \
                 patch.object(h.subprocess, 'Popen', side_effect=popen), \
                 patch.object(h, 'focus_window', return_value=''):
                assert not h.discover_live()[0], 'Isolated environment must start without projects'
                added = h.add_project(str(checkout))
                key = added['key']
                h.action(key, 'focus')
                live = h.find_project(key)
                assert live['open'], live
                snap = h.rpc(live['socket'], 'session.snapshot')['snapshot']
                assert len(snap['workspaces']) == 1, snap['workspaces']
                assert all(p['cwd'] == str(checkout) for p in snap['panes']), snap['panes']
                assert len(spawned) == 1, 'Cold start should launch exactly one server'
                h.action(key, 'focus')
                assert len(h.rpc(live['socket'], 'workspace.list')['workspaces']) == 1
                # Close only our test workspace and verify the saved row can recreate it.
                h.rpc(live['socket'], 'workspace.close', {'workspace_id': live['workspace_id']})
                assert not h.find_project(key)['open']
                h.action(key, 'focus')
                reopened = h.find_project(key)
                assert reopened['open'] and reopened['workspace_id'] != live['workspace_id']
                assert len(h.discover()[0]) == 1, 'Reopening must not duplicate the saved row'
                # Simulate absence of Herdr without touching its installation.
                with patch.dict(os.environ, {'PATH': str(shim)}):
                    result = h.action(key, 'focus')
                    data = json.loads(receipt.read_text())
                    assert data['cwd'] == str(checkout), data
                    assert '--dir=' + str(checkout) in data['argv'], data
                    assert 'herdr' not in data['argv'], data
                    assert 'default terminal' in result['message'], result
                print('PASS: native cold Herdr start, exact cwd, reuse, closed-project reopening, stable row, and no-Herdr default-terminal receipt.')
        finally:
            for child in spawned:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)


if __name__ == '__main__':
    check()
