import asyncio
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import die_server as server


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / '-sample file.exe'
        self.file.write_bytes(b'MZ')

    async def test_structure_calls_use_supported_flags(self):
        operations = [(server.get_file_info, 'Info'), (server.get_file_hashes, 'Hash'),
                      (server.get_file_entropy, 'Entropy'), (server.check_file_format, 'Check format')]
        with patch.object(server, 'run_die_command', return_value='{"data": {}}') as run:
            for tool, structure in operations:
                await tool(str(self.file))
                self.assertEqual(run.call_args.args, (str(self.file), ['--struct', structure, '--json']))
            await server.show_special_info(str(self.file), 'Hash#MD5')
            self.assertEqual(run.call_args.args[1], ['--struct', 'Hash#MD5', '--json'])
            await server.list_available_methods(str(self.file))
            self.assertEqual(run.call_args.args[1], ['--showstructs'])

    async def test_scan_modes_output_and_database_paths(self):
        with patch.object(server, 'run_die_command', return_value='output') as run:
            await server.analyze_file(str(self.file), deep_scan=True, heuristic_scan=True,
                                      aggressive_scan=True, all_types=True, profiling=True,
                                      messages=True, hide_unknown=True, output_format='xml',
                                      database_path=str(self.root))
            options = run.call_args.args[1]
            self.assertIn('--heuristicscan', options)
            self.assertIn('--aggressivecscan', options)
            self.assertIn('--xml', options)
            self.assertNotIn('--json', options)
            self.assertEqual(options[-2:], ['--database', str(self.root.resolve())])
            result = await server.analyze_file(str(self.file), output_format='invalid')
            self.assertTrue(result.startswith('Error:'))
            self.assertEqual(run.call_count, 1)
            result = await server.get_database_info(database_path=str(self.root / 'missing'))
            self.assertTrue(result.startswith('Error:'))
            self.assertEqual(run.call_count, 1)

    async def test_empty_output_format_is_rejected(self):
        with patch.object(server, 'run_die_command') as run:
            result = await server.analyze_file(str(self.file), output_format='')
            self.assertTrue(result.startswith('Error:'))
            run.assert_not_called()

    def test_directory_skips_windows_reparse_points(self):
        entry = SimpleNamespace(path=str(self.root / 'junction'),
                                stat=lambda **kwargs: SimpleNamespace(st_file_attributes=1024),
                                is_symlink=lambda: False)
        with patch.object(server.stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024, create=True), \
             patch.object(server.os, 'scandir') as scan, \
             patch.object(server, 'run_die_command') as run:
            scan.return_value.__enter__.return_value = iter([entry])
            result = json.loads(server.scan_directory(str(self.root), True, '*', 20, 60, ['--json']))
            self.assertTrue(result['complete'])
            self.assertEqual(result['scanned_files'], 0)
            run.assert_not_called()

    async def test_missing_inputs_do_not_launch_die(self):
        with patch.object(server, 'run_die_command') as run:
            self.assertTrue((await server.get_file_hashes(str(self.root / 'missing'))).startswith('Error:'))
            self.assertTrue((await server.analyze_directory(str(self.root), max_files=101)).startswith('Error:'))
            self.assertTrue((await server.analyze_directory(str(self.root), filename_pattern='../*')).startswith('Error:'))
            run.assert_not_called()

    async def test_slow_native_call_does_not_block_event_loop(self):
        def slow(*args):
            time.sleep(0.1)
            return 'done'
        with patch.object(server, 'run_die_command', side_effect=slow):
            task = asyncio.create_task(server.get_die_version())
            await asyncio.sleep(0.02)
            self.assertFalse(task.done())
            self.assertEqual(await task, 'done')

    async def test_directory_recursion_filter_and_file_limit(self):
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / 'child.exe').write_bytes(b'MZ')
        (self.root / 'ignore.txt').write_text('text')
        with patch.object(server, 'run_die_command', return_value='{"detects": []}'):
            result = json.loads(await server.analyze_directory(str(self.root), filename_pattern='*.exe'))
            self.assertEqual(result['scanned_files'], 1)
            self.assertTrue(result['complete'])
            result = json.loads(await server.analyze_directory(str(self.root), recursive=True,
                                                               filename_pattern='*.exe', max_files=1))
            self.assertEqual(result['scanned_files'], 1)
            self.assertFalse(result['complete'])
            self.assertEqual(result['stopped_reason'], 'file_limit')
            result = json.loads(await server.analyze_directory(str(self.root), recursive=True,
                                                               filename_pattern='*.exe'))
            self.assertEqual(result['scanned_files'], 2)
            self.assertTrue(result['complete'])

    async def test_directory_native_errors_and_output_limit(self):
        with patch.object(server, 'run_die_command', return_value='Error: timed out'):
            result = json.loads(await server.analyze_directory(str(self.root)))
            self.assertEqual(result['failed_files'], 1)
            self.assertIn('error', result['results'][0])
        with patch.object(server, 'run_die_command', return_value='x' * 1000001):
            result = json.loads(await server.analyze_directory(str(self.root)))
            self.assertEqual(result['stopped_reason'], 'output_limit')
            self.assertFalse(result['complete'])
            self.assertLess(len(json.dumps(result)), 1000000)

    async def test_directory_total_timeout(self):
        def slow(*args, **kwargs):
            time.sleep(0.02)
            return '{"detects": []}'
        with patch.object(server, 'run_die_command', side_effect=slow):
            result = json.loads(server.scan_directory(str(self.root), False, '*', 20, 0.01, ['--json']))
            self.assertEqual(result['stopped_reason'], 'timeout')
            self.assertFalse(result['complete'])

    def test_subprocess_errors_and_absolute_target(self):
        with patch.object(server.subprocess, 'run', return_value=SimpleNamespace(stdout='ok')) as run:
            self.assertEqual(server.run_die_command(str(self.file), ['--json']), 'ok')
            self.assertEqual(run.call_args.args[0][-1], str(self.file.resolve()))
            self.assertEqual(run.call_args.kwargs['timeout'], 120)
        with patch.object(server.subprocess, 'run', side_effect=subprocess.TimeoutExpired('diec', 2)):
            self.assertIn('timed out', server.run_die_command(None, ['--version'], timeout=2))
        with patch.object(server.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'diec', output='CLI error')):
            self.assertIn('CLI error', server.run_die_command(None, ['--version']))


if __name__ == '__main__':
    unittest.main()
