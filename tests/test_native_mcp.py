"""Opt-in native MCP integration test: set DIE_TEST_EXECUTABLE to diec.exe."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
import httpx

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = os.environ.get('DIE_TEST_EXECUTABLE')


@unittest.skipUnless(EXECUTABLE, 'Set DIE_TEST_EXECUTABLE for native integration tests')
class NativeMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_sse_tools(self):
        executable = str(Path(EXECUTABLE).resolve())
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        with tempfile.TemporaryFile(mode='w+') as log:
            process = subprocess.Popen([os.sys.executable, str(ROOT / 'scripts' / 'die_server.py'),
                '--die-path', executable, '--transport', 'sse', '--host', '127.0.0.1', '--port', str(port)],
                stdout=log, stderr=log)
            try:
                async with httpx.AsyncClient() as client:
                    for attempt in range(100):
                        try:
                            await client.get(url, timeout=0.5)
                            break
                        except httpx.TransportError:
                            if process.poll() is not None:
                                self.fail('SSE server exited before accepting connections')
                            await asyncio.sleep(0.1)
                    else:
                        self.fail('SSE server did not become ready')
                async with sse_client(url + '/sse') as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        cases = [('get_die_version', {}, ['--version'], False),
                                 ('get_database_info', {}, ['--showdatabase'], False),
                                 ('analyze_file', {'file_path': executable}, ['--json'], True),
                                 ('list_available_methods', {'file_path': executable}, ['--showstructs'], True)]
                        for tool, method in [('get_file_info', 'Info'), ('get_file_hashes', 'Hash'),
                                             ('get_file_entropy', 'Entropy'), ('check_file_format', 'Check format'),
                                             ('show_special_info', 'Hash#MD5')]:
                            arguments = {'file_path': executable}
                            if tool == 'show_special_info':
                                arguments['method'] = method
                            cases.append((tool, arguments, ['--struct', method, '--json'], True))
                        for tool, arguments, flags, targeted in cases:
                            result = await asyncio.wait_for(session.call_tool(tool, arguments), 125)
                            self.assertFalse(result.isError)
                            actual = ''.join(item.text for item in result.content if item.type == 'text')
                            native = await asyncio.to_thread(subprocess.run,
                                [executable, *flags, *([executable] if targeted else [])],
                                cwd=str(Path(executable).parent), capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=120)
                            self.assertEqual(native.returncode, 0)
                            self.assertEqual(actual, native.stdout)
                        result = await session.call_tool('analyze_directory', {
                            'directory_path': str(Path(executable).parent), 'filename_pattern': Path(executable).name})
                        self.assertFalse(result.isError)
                        batch = json.loads(''.join(item.text for item in result.content if item.type == 'text'))
                        self.assertEqual(batch['scanned_files'], 1)
                        self.assertEqual(batch['failed_files'], 0)
                        self.assertTrue(batch['complete'])
                        self.assertEqual(names, {case[0] for case in cases} | {'analyze_directory'})
                        print('PASS all 10 tools over loopback SSE', flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

    async def test_all_tools_native_parity_and_edge_cases(self):
        executable = Path(EXECUTABLE).resolve()
        self.assertTrue(executable.is_file())
        calls = 0
        exercised = set()

        def native(flags, target=None):
            args = [str(executable), *flags]
            if target is not None:
                args.append(str(Path(target).resolve()))
            result = subprocess.run(args, cwd=executable.parent, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            return result.stdout

        with tempfile.TemporaryDirectory(prefix='die-mcp-test-') as directory, tempfile.TemporaryFile(mode='w+') as log:
            root = Path(directory)
            fixtures = [root / 'empty.bin', root / '-text sample ü.txt', root / 'truncated.exe', root / 'sample.zip']
            fixtures[0].write_bytes(b'')
            fixtures[1].write_text('A plain text fixture.\n' * 20, encoding='utf-8')
            fixtures[2].write_bytes(b'MZ' + bytes(62))
            with zipfile.ZipFile(fixtures[3], 'w') as archive:
                archive.writestr('sample.txt', 'Read-only MCP test')
            nested = root / 'nested'
            nested.mkdir()
            (nested / 'child.txt').write_text('nested fixture')
            parameters = StdioServerParameters(command=os.sys.executable,
                args=[str(ROOT / 'scripts' / 'die_server.py'), '--die-path', str(executable)])
            async with stdio_client(parameters, errlog=log) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = {tool.name for tool in listed.tools}
                    self.assertEqual(len(names), 10)

                    async def call(name, **arguments):
                        nonlocal calls
                        result = await asyncio.wait_for(session.call_tool(name, arguments), 125)
                        self.assertFalse(result.isError, str(result))
                        calls += 1
                        exercised.add(name)
                        return ''.join(item.text for item in result.content if item.type == 'text')

                    async def parity(name, flags, target=None, **arguments):
                        actual = await call(name, **arguments)
                        expected = await asyncio.to_thread(native, flags, target)
                        try:
                            self.assertEqual(json.loads(actual), json.loads(expected), name)
                        except json.JSONDecodeError:
                            self.assertEqual(actual, expected, name)
                        return actual

                    await parity('get_die_version', ['--version'])
                    await parity('get_database_info', ['--showdatabase'])
                    wrappers = [('get_file_info', 'Info'), ('get_file_hashes', 'Hash'),
                                ('get_file_entropy', 'Entropy'), ('check_file_format', 'Check format')]
                    for target in [executable, *fixtures]:
                        await parity('analyze_file', ['--json'], target, file_path=str(target))
                        methods = await parity('list_available_methods', ['--showstructs'], target, file_path=str(target))
                        for tool, method in wrappers:
                            output = await parity(tool, ['--struct', method, '--json'], target, file_path=str(target))
                            special = await call('show_special_info', file_path=str(target), method=method)
                            self.assertEqual(json.loads(output), json.loads(special))
                            if tool == 'get_file_hashes' and target.stat().st_size:
                                hashes = json.loads(output)['data']['Hash']
                                for algorithm in ['md5', 'sha1', 'sha256', 'sha512']:
                                    self.assertEqual(hashes[algorithm.upper()].lower(),
                                        hashlib.new(algorithm, target.read_bytes()).hexdigest())
                        for method in [line.strip() for line in methods.splitlines()[1:] if line.strip()]:
                            await parity('show_special_info', ['--struct', method, '--json'], target,
                                         file_path=str(target), method=method)
                        print('PASS file and structure parity:', target.name, flush=True)

                    flags = [('deep_scan', '--deepscan'), ('heuristic_scan', '--heuristicscan'),
                             ('aggressive_scan', '--aggressivecscan'), ('entropy', '--entropy'),
                             ('verbose', '--verbose'), ('all_types', '--alltypes'),
                             ('profiling', '--profiling'), ('messages', '--messages'),
                             ('hide_unknown', '--hideunknown')]
                    for option, flag in flags:
                        await parity('analyze_file', ['--json', flag], executable,
                                     file_path=str(executable), **{option: True})
                    for output_format in ['json', 'xml', 'csv', 'tsv', 'plaintext']:
                        output = await parity('analyze_file', ['--' + output_format], executable,
                                             file_path=str(executable), output_format=output_format, json_output=False)
                        if output_format == 'xml':
                            ET.fromstring(output)
                    await parity('analyze_file', ['--plaintext'], executable,
                                 file_path=str(executable), json_output=False)
                    for argument, flag in [('database_path', '--database'),
                                           ('extra_database_path', '--extradatabase'),
                                           ('custom_database_path', '--customdatabase')]:
                        database = executable.parent / {'database_path': 'db', 'extra_database_path': 'db_extra',
                                                         'custom_database_path': 'db_custom'}[argument]
                        if not database.is_dir():
                            database = root / argument
                            database.mkdir()
                        await parity('get_database_info', ['--showdatabase', flag, str(database)],
                                     **{argument: str(database)})
                        await parity('analyze_file', ['--json', flag, str(database)], executable,
                                     file_path=str(executable), **{argument: str(database)})
                    print('PASS scan flags, formats and database overrides', flush=True)

                    for recursive, count in [(False, 4), (True, 5)]:
                        batch = json.loads(await call('analyze_directory', directory_path=str(root), recursive=recursive))
                        self.assertTrue(batch['complete'])
                        self.assertEqual(batch['scanned_files'], count)
                        self.assertEqual(batch['failed_files'], 0)
                        for item in batch['results']:
                            single = json.loads(await call('analyze_file', file_path=item['file_path']))
                            self.assertEqual(item['result'], single)
                    for arguments, count, reason in [({'filename_pattern': '*.zip'}, 1, None),
                                                    ({'filename_pattern': '*.missing'}, 0, None),
                                                    ({'max_files': 1}, 1, 'file_limit'),
                                                    ({'entropy': True, 'filename_pattern': '*.zip'}, 1, None)]:
                        batch = json.loads(await call('analyze_directory', directory_path=str(root), **arguments))
                        self.assertEqual(batch['scanned_files'], count)
                        self.assertEqual(batch['stopped_reason'], reason)
                        if arguments.get('entropy'):
                            item = batch['results'][0]
                            single = json.loads(await call('analyze_file', file_path=item['file_path'], entropy=True))
                            self.assertEqual(item['result'], single)
                    for tool in ['analyze_file', 'list_available_methods', *[item[0] for item in wrappers], 'show_special_info']:
                        arguments = {'file_path': str(root / 'missing')}
                        if tool == 'show_special_info':
                            arguments['method'] = 'Info'
                        self.assertTrue((await call(tool, **arguments)).startswith('Error:'))
                        arguments['file_path'] = str(root)
                        self.assertTrue((await call(tool, **arguments)).startswith('Error:'))
                    for output in ['', 'invalid', 'JSON']:
                        self.assertTrue((await call('analyze_file', file_path=str(executable), output_format=output)).startswith('Error:'))
                    self.assertTrue((await call('show_special_info', file_path=str(executable), method=' ')).startswith('Error:'))
                    await parity('show_special_info', ['--struct', 'unknown-method', '--json'], executable,
                                 file_path=str(executable), method='unknown-method')
                    for arguments in [{'max_files': 0}, {'max_files': 101}, {'timeout_seconds': 0},
                                      {'timeout_seconds': 301}, {'filename_pattern': ''}, {'filename_pattern': '../*'}]:
                        self.assertTrue((await call('analyze_directory', directory_path=str(root), **arguments)).startswith('Error:'))
                    self.assertTrue((await call('analyze_directory', directory_path=str(root / 'missing'))).startswith('Error:'))
                    for tool in ['get_database_info', 'analyze_file', 'analyze_directory']:
                        arguments = {'database_path': str(root / 'missing')}
                        if tool == 'analyze_file':
                            arguments['file_path'] = str(executable)
                        if tool == 'analyze_directory':
                            arguments['directory_path'] = str(root)
                        self.assertTrue((await call(tool, **arguments)).startswith('Error:'))
                    bad = await session.call_tool('analyze_file', {'file_path': str(executable), 'deep_scan': 'invalid'})
                    self.assertTrue(bad.isError)
                    self.assertEqual(exercised, names)
                    print(f'PASS {calls} MCP calls; all {len(exercised)} tools; native parity and edge cases', flush=True)


if __name__ == '__main__':
    unittest.main()
