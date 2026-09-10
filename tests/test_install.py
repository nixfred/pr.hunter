import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install


class InstallerTests(unittest.TestCase):
    def test_preserves_settings_order_and_input(self):
        base = {'custom': {'keep': True}, 'bar': {'layout': {'left': ['clock', 'audio'],
                'right': [{'id': 'battery'}, {'id': 'network', 'zone': 'outer'}]}},
                'disabledPlugins': ['other', install.PLUGIN_ID]}
        before = copy.deepcopy(base)
        result = install.edited_config(base)
        self.assertEqual(base, before)
        self.assertEqual(result['bar']['layout']['left'], base['bar']['layout']['left'])
        self.assertEqual([p['id'] for p in result['bar']['layout']['right']], ['battery', install.PLUGIN_ID, 'network'])
        self.assertEqual(result['custom'], base['custom'])
        self.assertEqual(result['disabledPlugins'], ['other'])

    def test_existing_install_without_disabled_key_is_noop(self):
        base = {'bar': {'layout': {'right': [install.PLUGIN_ID]}}}
        self.assertEqual(install.edited_config(base), base)

    def test_install_edit_is_idempotent(self):
        base = {'bar': {'layout': {'left': ['a'], 'right': ['b']}}}
        edited = install.edited_config(base)
        self.assertEqual(install.edited_config(edited), edited)


if __name__ == '__main__':
    unittest.main()
