import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from scripts import configure


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'client.config'
        self.values = configure.defaults()
        executable = Path(self.temp.name) / 'diec.exe'
        executable.write_bytes(b'test fixture; not executed')
        self.values['die_path'] = str(executable)

    def test_json_clients_preserve_unrelated_settings_and_backup(self):
        for client in ('Claude Desktop', 'Claude Code'):
            original = {'preferences': {'theme': 'dark'}, 'mcpServers': {'other': {'command': 'keep'}}}
            raw = json.dumps(original)
            self.path.write_text(raw)
            configure.register(client, self.values, self.path)
            actual = json.loads(self.path.read_text())
            self.assertEqual(actual['preferences'], original['preferences'])
            self.assertEqual(actual['mcpServers']['other'], original['mcpServers']['other'])
            self.assertEqual(actual['mcpServers']['die']['args'][0], str(configure.SCRIPTS / 'die_server.py'))
            self.assertTrue(any(p.read_text() == raw for p in self.path.parent.glob('*.bak')))

    def test_codex_preserves_comments_and_other_tables(self):
        raw = '# my config\nmodel = "keep"\n[mcp_servers.other]\ncommand = "other"\n[mcp_servers."die"]\ncommand = "old"\n[mcp_servers.die.env]\nOLD = "old"\n[features]\nkeep = true\n'
        self.path.write_text(raw)
        configure.register('Codex', self.values, self.path)
        actual = self.path.read_text()
        expected = tomllib.loads(raw)
        expected['mcp_servers']['die'] = configure.entry(self.values)
        self.assertEqual(tomllib.loads(actual), expected)
        self.assertIn('# my config', actual)
        configure.register('Codex', self.values, self.path)
        self.assertEqual(self.path.read_text(), actual)

    def test_invalid_configs_are_not_overwritten(self):
        for client, raw in [('Claude Desktop', '{broken'), ('Claude Code', '{"mcpServers": []}'), ('Codex', '[broken')]:
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                configure.register(client, self.values, self.path)
            self.assertEqual(self.path.read_text(), raw)

    def test_inline_codex_layout_fails_without_losing_settings(self):
        raw = 'mcp_servers = {die = {command = "old"}, other = {command = "keep"}}\n'
        self.path.write_text(raw)
        with self.assertRaises(ValueError):
            configure.register('Codex', self.values, self.path)
        self.assertEqual(self.path.read_text(), raw)

    def test_validation_rejects_missing_executable_and_invalid_port(self):
        values = copy.deepcopy(self.values)
        values['python'] = str(self.path.parent / 'missing.exe')
        with self.assertRaises(ValueError):
            configure.validate(values)
        values = copy.deepcopy(self.values)
        values['port'] = '65536'
        with self.assertRaises(ValueError):
            configure.validate(values)


if __name__ == '__main__':
    unittest.main()
