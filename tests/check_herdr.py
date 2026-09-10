"""Native Herdr transport test in a temporary server; never sends to real agents."""
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_hunter as h


def check():
    with tempfile.TemporaryDirectory(prefix='pr-hunter-herdr-test-') as directory:
        temp = Path(directory)
        cfg = temp / 'config.toml'
        cfg.write_text('onboarding = false\n[terminal]\ndefault_shell = "/bin/sh"\n'
                       '[update]\nversion_check = false\nmanifest_check = false\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}
        # HERDR_CONFIG_PATH alone isolates the socket but NOT session.json.
        for name, folder in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                             ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache')]:
            env[name] = str(temp / folder)
        env['HERDR_CONFIG_PATH'] = str(cfg)
        env['HERDR_SOCKET_PATH'] = str(temp / 'herdr.sock')
        h.STATE = temp / 'state'
        with (temp / 'server.log').open('w') as log:
            server = subprocess.Popen(['herdr', 'server'], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            try:
                sock = env['HERDR_SOCKET_PATH']
                for _ in range(60):
                    try:
                        h.rpc(sock, 'ping')
                        break
                    except (OSError, h.Failure):
                        time.sleep(.1)
                else:
                    raise RuntimeError((temp / 'server.log').read_text()[-2000:])
                # The foreground program is a harmless stdin recorder, not a shell.
                assert not h.rpc(sock, 'workspace.list')['workspaces'], 'Test server must start empty'
                sink = temp / 'claude'
                received = temp / 'received.txt'
                source = temp / 'sink.c'
                source.write_text('#include <stdio.h>\nint main(int argc,char **argv){char line[65536];'
                                  'puts("TEST READY");fflush(stdout);while(fgets(line,sizeof(line),stdin)){'
                                  'FILE *f=fopen(argv[1],"w");if(!f)return 2;fputs(line,f);fclose(f);'
                                  'puts("RECEIVED");fflush(stdout);}return 0;}\n')
                subprocess.run(['cc', '-o', str(sink), str(source)], check=True, capture_output=True)
                output = subprocess.run(['herdr', 'workspace', 'create', '--label', 'PR Hunter Test',
                                         '--cwd', directory, '--no-focus'],
                                        env=env, text=True, capture_output=True, check=True)
                created = json.loads(output.stdout)['result']
                pane = created['root_pane']['pane_id']
                wid = created['workspace']['workspace_id']
                subprocess.run(['herdr', 'pane', 'run', pane, 'exec ' + shlex.join([str(sink), str(received)])],
                               env=env, text=True, capture_output=True, check=True)
                time.sleep(.4)
                h.rpc(sock, 'pane.report_agent', {'pane_id': pane, 'source': 'pr-hunter-test', 'agent': 'claude',
                                                'state': 'idle', 'agent_session_id': 'isolated-test', 'seq': 1})
                agents = h.rpc(sock, 'agent.list')['agents']
                agent = next(a for a in agents if a['pane_id'] == pane)
                project = {'label': 'Isolated test', 'socket': sock, 'session': 'isolated', 'workspace_id': wid}
                item = {'url': 'https://github.com/example/test/issues/1', 'updated': 'test', 'kind': 'Issue',
                        'repo': 'example/test', 'number': 1, 'title': 'Transport test', 'draft': False}
                brief = temp / 'brief.md'
                brief.write_text('Test transport only. No work requested.')
                job = {'id': 'test', 'identity': h.agent_identity(agent), 'brief': str(brief), 'items': [item], 'status': 'queued'}
                ledger = {'sent': {}, 'jobs': {'test': job}}
                h.rpc(sock, 'agent.focus', {'target': pane})
                h.send_job(project, job, ledger)
                assert job['status'] == 'sent', job
                for _ in range(50):
                    if received.exists():
                        break
                    time.sleep(.1)
                text = received.read_text()
                assert 'PR Hunter: process 1 selected PRs/issues' in text, text
                assert str(brief) in text, text
                snap = h.rpc(sock, 'session.snapshot')['snapshot']
                assert next(w for w in snap['workspaces'] if w['focused'])['workspace_id'] == wid
                # A later, new workspace is visible without a restart or configuration edit.
                h.rpc(sock, 'workspace.create', {'label': 'Added later', 'cwd': directory, 'focus': False})
                snap = h.rpc(sock, 'session.snapshot')['snapshot']
                assert any(w['label'] == 'Added later' for w in snap['workspaces'])
                print('PASS: native workspace discovery, focus, agent identity, prompt delivery and later project discovery in an isolated Herdr server.')
            finally:
                # Only our Popen child. No command ever targets the production server.
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == '__main__':
    check()
