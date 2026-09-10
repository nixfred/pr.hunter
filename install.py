#!/usr/bin/env python3
"""Link PR Hunter and add one bar entry using Omarchy's live compare-and-set API."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
PLUGIN_ID = 'nixfred.pr-hunter'


def edited_config(base):
    edited = copy.deepcopy(base)
    layout = edited.setdefault('bar', {}).setdefault('layout', {})
    if not any((e.get('id') if isinstance(e, dict) else e) == PLUGIN_ID for entries in layout.values() for e in entries):
        right = layout.setdefault('right', [])
        index = next((i for i, e in enumerate(right) if isinstance(e, dict) and e.get('zone') == 'outer'), len(right))
        right.insert(index, {'id': PLUGIN_ID, 'zone': 'outer'})
    edited['disabledPlugins'] = [p for p in edited.get('disabledPlugins', []) if p != PLUGIN_ID]
    return edited


def main():
    subprocess.run(['omarchy', 'plugin', 'validate', str(ROOT)], check=True)
    plugin_root = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'omarchy/plugins'
    plugin_root.mkdir(parents=True, exist_ok=True)
    target = plugin_root / PLUGIN_ID
    if target.exists() or target.is_symlink():
        if target.resolve() != ROOT:
            raise SystemExit(f'Refusing to replace another installation: {target}')
    else:
        target.symlink_to(ROOT, target_is_directory=True)
    subprocess.run(['omarchy-shell', 'shell', 'rescanPlugins'], check=True)
    with tempfile.TemporaryDirectory(prefix='pr-hunter-install-') as d:
        base, edited = Path(d) / 'base.json', Path(d) / 'edited.json'
        for attempt in range(3):
            try:
                subprocess.run(['omarchy', 'shell', 'config-edit', 'snapshot', str(base)], check=True)
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise
                time.sleep(1)
                continue
            original = json.loads(base.read_text())
            desired = edited_config(original)
            if desired == original:
                print('PR Hunter is already in the live bar.')
                break
            edited.write_text(json.dumps(desired, indent=2) + '\n')
            result = subprocess.run(['omarchy', 'shell', 'config-edit', 'apply', str(base), str(edited), '--allow-layout-change'],
                                    text=True, capture_output=True)
            if result.returncode == 0:
                print(result.stdout.strip())
                break
            # Adding a plugin can hot-reload the shell after it accepted the
            # configuration but before the CLI's persistence probe. Re-read
            # live state to verify the result; never replay the old snapshot.
            retryable = ('changed since', 'changed during', 'not responding', 'returned non-zero exit status', 'timed out')
            if not any(reason in result.stderr for reason in retryable):
                raise SystemExit(result.stderr)
            if attempt == 2:
                raise SystemExit('Configuration kept changing. Rerun the installer; no stale configuration was forced.')
            time.sleep(.2)
    print(f'Installed {PLUGIN_ID}. Open with: omarchy-shell {PLUGIN_ID} open')


if __name__ == '__main__':
    main()
