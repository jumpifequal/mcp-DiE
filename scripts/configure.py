"""Shared settings, safe client registration, and MCP diagnostics (Python 3.11+)."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
SETTINGS = ROOT / 'die-mcp-settings.json'
DEFAULT_DIE = r'C:\Program Files\DiE\diec.exe'
CLIENTS = ('Claude Desktop', 'Claude Code', 'Codex')
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def defaults():
    venv = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return {'python': str(venv if venv.is_file() else Path(sys.executable)),
            'die_path': DEFAULT_DIE, 'name': 'die', 'host': '127.0.0.1', 'port': 8080}


def load_settings():
    values = defaults()
    if SETTINGS.exists():
        saved = json.loads(SETTINGS.read_text(encoding='utf-8-sig'))
        if not isinstance(saved, dict):
            raise ValueError('Settings must be a JSON object')
        values.update({k: v for k, v in saved.items() if k in values})
    return values


def validate(values):
    for key in ('python', 'die_path'):
        path = Path(os.path.expandvars(os.path.expanduser(values[key])))
        if not path.is_file():
            raise ValueError(f'{key}: file not found: {path}')
        values[key] = str(path.resolve())
    if not re.fullmatch(r'[A-Za-z0-9_-]+', values['name']):
        raise ValueError('Server name must contain only letters, numbers, _ or -')
    if values['host'] not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('The console supports local loopback hosts only')
    values['port'] = int(values['port'])
    if not 1 <= values['port'] <= 65535:
        raise ValueError('Port must be between 1 and 65535')
    return values


def atomic_write(path, text, backup=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and path.exists():
        backup_path = path.with_name(path.name + '.' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.bak')
        backup_path.write_bytes(path.read_bytes())
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup_path


def save_settings(values):
    validate(values)
    atomic_write(SETTINGS, json.dumps(values, indent=2) + '\n')


def server_command(values, transport='stdio'):
    return [values['python'], str(SCRIPTS / 'die_server.py'), '--die-path', values['die_path'],
            '--transport', transport]


def client_path(client):
    if client == 'Claude Desktop':
        return Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'Claude/claude_desktop_config.json'
    if client == 'Claude Code':
        return Path.home() / '.claude.json'
    if client == 'Codex':
        return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
    raise ValueError(f'Unknown client: {client}')


def entry(values):
    command, *args = server_command(values)
    return {'command': command, 'args': args}


def preview(client, values):
    registration = entry(values)
    if client != 'Codex':
        if client == 'Claude Code':
            registration = {'type': 'stdio', **registration}
        return json.dumps({'mcpServers': {values['name']: registration}}, indent=2) + '\n'
    return (f'[mcp_servers.{values["name"]}]\ncommand = {json.dumps(registration["command"])}\n'
            f'args = {json.dumps(registration["args"])}\n')


def merge_codex(text, values):
    """Replace only this server's tables; preserve other text and verify semantics."""
    before = tomllib.loads(text)
    name = values['name']
    lines = text.splitlines(keepends=True)
    result = []
    skip = False
    for line in lines:
        if re.match(r'^\s*\[', line):
            try:
                header = tomllib.loads(line)
            except tomllib.TOMLDecodeError:
                # This may be a multiline string or array: final semantic check protects it.
                header = {}
            skip = name in header.get('mcp_servers', {})
        if not skip:
            result.append(line)
    merged = ''.join(result).rstrip() + '\n\n' + preview('Codex', values)
    after = tomllib.loads(merged)
    expected = copy.deepcopy(before)
    expected.setdefault('mcp_servers', {})[name] = entry(values)
    if after != expected:
        raise ValueError('Cannot safely update this TOML layout. Copy the preview into the configuration manually.')
    return merged


def register(client, values, destination=None):
    validate(values)
    path = Path(destination) if destination else client_path(client)
    old = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    if client == 'Codex':
        updated = merge_codex(old, values)
    else:
        data = json.loads(old) if old.strip() else {}
        if not isinstance(data, dict) or not isinstance(data.get('mcpServers', {}), dict):
            raise ValueError('Client config and mcpServers must be JSON objects')
        registration = entry(values)
        if client == 'Claude Code':
            registration = {'type': 'stdio', **registration}
        data.setdefault('mcpServers', {})[values['name']] = registration
        updated = json.dumps(data, indent=2) + '\n'
    backup = atomic_write(path, updated, backup=True)
    return f'Updated {path}' + (f'\nBackup: {backup}' if backup else '')


def dependency_check(values):
    result = subprocess.run([values['python'], '-c', 'import mcp, uvicorn, starlette; print("MCP dependencies available")'],
                            capture_output=True, text=True, timeout=20, creationflags=FLAGS)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() + '\nUse Install dependencies in the console.')
    return result.stdout.strip()


def install_dependencies(values):
    result = subprocess.run([values['python'], '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')],
                            capture_output=True, text=True, timeout=300, creationflags=FLAGS)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout + result.stderr


def self_test(values):
    validate(values)
    dependency_check(values)
    code = r'''
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def probe():
    params = StdioServerParameters(command=sys.argv[1], args=sys.argv[2:])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            required = {'analyze_file', 'show_special_info', 'list_available_methods',
                        'get_file_info', 'get_file_hashes', 'get_file_entropy', 'check_file_format',
                        'get_die_version', 'get_database_info', 'analyze_directory'}
            if not required <= names:
                raise RuntimeError(f'Missing tools: {required - names}')
            print('MCP initialized. Tools: ' + ', '.join(sorted(names)))
asyncio.run(asyncio.wait_for(probe(), timeout=20))
'''
    result = subprocess.run([values['python'], '-c', code, *server_command(values)],
                            capture_output=True, text=True, timeout=30, creationflags=FLAGS)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def wizard():
    print('DiE MCP setup — Python 3.11+\n')
    values = load_settings()
    for key, label in [('python', 'Python executable'), ('die_path', 'DiE executable'), ('name', 'MCP server name')]:
        answer = input(f'{label} [{values[key]}]: ').strip().strip('"')
        if answer:
            values[key] = answer
    validate(values)
    try:
        print(dependency_check(values))
    except RuntimeError as error:
        print(error)
        if input('Install dependencies into this Python? [y/N]: ').lower() != 'y':
            return
        print(install_dependencies(values))
    print(self_test(values))
    save_settings(values)
    print('\n1. Claude Desktop\n2. Claude Code (user scope)\n3. Codex\n4. All\n0. Save settings only')
    choice = input('Client [4]: ').strip() or '4'
    if choice not in ('0', '1', '2', '3', '4'):
        raise ValueError('Choose 0, 1, 2, 3 or 4')
    clients = CLIENTS if choice == '4' else (() if choice == '0' else (CLIENTS[int(choice)-1],))
    for client in clients:
        print(f'\n{client}: {client_path(client)}\n{preview(client, values)}')
        if input('Write this entry (existing file backed up)? [Y/n]: ').lower() != 'n':
            print(register(client, values))
    print('\nFinished. Restart affected clients to load the server. Open console.bat for the GUI.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Interactive DiE MCP setup')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    try:
        if args.self_test:
            print(self_test(load_settings()))
        else:
            wizard()
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, EOFError) as error:
        print(f'Setup failed: {error}', file=sys.stderr)
        sys.exit(1)
