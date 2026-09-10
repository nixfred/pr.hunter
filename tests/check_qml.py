"""Run the real QML service against a fake helper in a checkout with spaces."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check():
    with tempfile.TemporaryDirectory(prefix='pr hunter qml ') as directory:
        temp = Path(directory)
        shutil.copyfile(ROOT / 'Service.qml', temp / 'Service.qml')
        (temp / 'pr_hunter.py').write_text('''import json, pathlib, sys, time
root = pathlib.Path(__file__).parent
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
command = sys.argv[1]
if command == 'scan':
    time.sleep(.2)
    print(json.dumps({'projects':[{'key':'key'}], 'errors':[]}))
elif command == 'hang':
    time.sleep(20)
else:
    print('A harmless stderr diagnostic', file=sys.stderr)
    print(json.dumps({'message':'Action accepted'}))
''')
        (temp / 'shell.qml').write_text('''import QtQuick
import Quickshell
ShellRoot {
    Service { id: bridge; helperTimeout: 2000 }
    property int stage: 0
    Timer {
        interval: 40; running: true; repeat: true
        onTriggered: {
            if (stage === 0 && bridge.refreshing) {
                bridge.act("map", "key", "mine", "pane", "-h")
                if (!bridge.busy) throw new Error("Action was not queued")
                stage = 1
            } else if (stage === 1 && bridge.message === "Action accepted" && !bridge.refreshing && !bridge.busy) {
                if (bridge.lastError !== "" || bridge.projects.length !== 1 || bridge.projects[0].repos.length !== 0)
                    throw new Error("Snapshot normalization or stdio failed")
                bridge.helperTimeout = 150
                bridge.act("hang", "key", "all", "", "")
                stage = 2
            } else if (stage === 2 && bridge.message.indexOf("timed out") >= 0) {
                console.log("PASS: QML decoded path, serialized action, option value, normalized snapshot, stdio and watchdog")
                Qt.quit()
            }
        }
    }
    Timer { interval: 6000; running: true; onTriggered: { console.log("FAIL: QML service stalled"); Qt.quit() } }
}
''')
        env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QPA_PLATFORMTHEME': 'generic', 'XDG_CACHE_HOME': str(temp / 'cache'),
               'XDG_RUNTIME_DIR': str(temp / 'runtime')}
        (temp / 'runtime').mkdir(mode=0o700)
        p = subprocess.run(['quickshell', '-p', str(temp / 'shell.qml')], env=env,
                           capture_output=True, text=True, timeout=10)
        output = p.stdout + p.stderr
        assert 'PASS: QML' in output, output
        calls = [json.loads(line) for line in (temp / 'calls.jsonl').read_text().splitlines()]
        assert [c[0] for c in calls[:3]] == ['scan', 'map', 'scan'], calls
        assert '--path=-h' in calls[1], calls
        print(next(line for line in output.splitlines() if 'PASS: QML' in line))


if __name__ == '__main__':
    check()
