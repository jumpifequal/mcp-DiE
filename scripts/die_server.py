"""Read-only Detect It Easy tools exposed through MCP."""
import asyncio
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import stat
import time
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
import uvicorn

mcp = FastMCP('die')
DIE_EXECUTABLE = os.environ.get('DIE_EXECUTABLE', r'C:\Program Files\DiE\diec.exe')
OUTPUT_FORMATS = ('json', 'xml', 'csv', 'tsv', 'plaintext')


def run_die_command(target_path: Optional[str], options: List[str], timeout: float = 120) -> str:
    """Run DiE with separate arguments and a bounded execution time."""
    cmd = [DIE_EXECUTABLE] + options
    if target_path is not None:
        cmd.append(str(Path(target_path).resolve()))
    executable_dir = str(Path(DIE_EXECUTABLE).resolve().parent) if os.path.dirname(DIE_EXECUTABLE) else None
    try:
        result = subprocess.run(cmd, cwd=executable_dir, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', check=True, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return result.stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr or error.stdout or str(error)
        return f'Error executing DIE (exit {error.returncode}, 0x{error.returncode & 0xffffffff:08X}): {detail}'
    except subprocess.TimeoutExpired:
        return f'Error: DIE operation timed out after {timeout:g} seconds.'
    except FileNotFoundError:
        return f"Error: DIE executable not found at '{DIE_EXECUTABLE}'. Please set the correct path."
    except OSError as error:
        return f'Error executing DIE: {error}'


def database_options(database_path=None, extra_database_path=None, custom_database_path=None):
    options = []
    for flag, value in (('--database', database_path), ('--extradatabase', extra_database_path),
                        ('--customdatabase', custom_database_path)):
        if value is not None:
            path = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
            if not path.is_dir():
                raise ValueError(f'Database directory not found: {path}')
            options.extend([flag, str(path)])
    return options


def scan_options(json_output=True, deep_scan=False, entropy=False, verbose=False,
                 heuristic_scan=False, aggressive_scan=False, all_types=False,
                 profiling=False, messages=False, hide_unknown=False, output_format=None,
                 database_path=None, extra_database_path=None, custom_database_path=None):
    output = output_format if output_format is not None else ('json' if json_output else 'plaintext')
    if output not in OUTPUT_FORMATS:
        raise ValueError('output_format must be one of: ' + ', '.join(OUTPUT_FORMATS))
    options = ['--' + output]
    for enabled, flag in ((deep_scan, '--deepscan'), (entropy, '--entropy'), (verbose, '--verbose'),
                          (heuristic_scan, '--heuristicscan'), (aggressive_scan, '--aggressivecscan'),
                          (all_types, '--alltypes'), (profiling, '--profiling'),
                          (messages, '--messages'), (hide_unknown, '--hideunknown')):
        if enabled:
            options.append(flag)
    return options + database_options(database_path, extra_database_path, custom_database_path)


@mcp.tool()
async def analyze_file(file_path: str, json_output: bool = True, deep_scan: bool = False,
                       entropy: bool = False, verbose: bool = False, heuristic_scan: bool = False,
                       aggressive_scan: bool = False, all_types: bool = False, profiling: bool = False,
                       messages: bool = False, hide_unknown: bool = False, output_format: Optional[str] = None,
                       database_path: Optional[str] = None, extra_database_path: Optional[str] = None,
                       custom_database_path: Optional[str] = None) -> str:
    """Identify file format, compiler, packer, and protection with optional scan modes.

    output_format overrides json_output and accepts json, xml, csv, tsv, or plaintext.
    entropy=True selects a detailed entropy report instead of detections.
    messages=True can prepend native warnings, making JSON/XML unsuitable for direct parsing.
    Database paths select signature directories for this call only.
    """
    if not os.path.isfile(file_path):
        return f"Error: File not found at path '{file_path}'"
    try:
        options = scan_options(json_output, deep_scan, entropy, verbose, heuristic_scan, aggressive_scan,
                               all_types, profiling, messages, hide_unknown, output_format,
                               database_path, extra_database_path, custom_database_path)
    except (ValueError, OSError) as error:
        return f'Error: {error}'
    return await asyncio.to_thread(run_die_command, file_path, options)


@mcp.tool()
async def show_special_info(file_path: str, method: str) -> str:
    """Read a DiE structure, such as Info, Hash, Hash#MD5, Entropy, or Check format.

    Unknown or unsupported structures preserve DiE's empty data result.
    """
    if not os.path.isfile(file_path):
        return f"Error: File not found at path '{file_path}'"
    if not method.strip():
        return 'Error: method must name a DiE structure.'
    return await asyncio.to_thread(run_die_command, file_path, ['--struct', method, '--json'])


@mcp.tool()
async def list_available_methods(file_path: str) -> str:
    """List the special structures supported for this file. DiE returns plain text."""
    if not os.path.isfile(file_path):
        return f"Error: File not found at path '{file_path}'"
    return await asyncio.to_thread(run_die_command, file_path, ['--showstructs'])


@mcp.tool()
async def get_file_info(file_path: str) -> str:
    """Return JSON metadata including format, architecture, OS, size, and MIME type."""
    return await show_special_info(file_path, 'Info')


@mcp.tool()
async def get_file_hashes(file_path: str) -> str:
    """Return JSON hashes supported by DiE, including MD5, SHA-256, and SHA-512.

    Native empty hash values, such as those for empty files in DiE 3.21, are preserved.
    """
    return await show_special_info(file_path, 'Hash')


@mcp.tool()
async def get_file_entropy(file_path: str) -> str:
    """Return the file entropy structure as JSON."""
    return await show_special_info(file_path, 'Entropy')


@mcp.tool()
async def check_file_format(file_path: str) -> str:
    """Return DiE's format-check structure as JSON. An empty result is preserved."""
    return await show_special_info(file_path, 'Check format')


@mcp.tool()
async def get_die_version() -> str:
    """Return the installed DiE CLI version."""
    return await asyncio.to_thread(run_die_command, None, ['--version'])


@mcp.tool()
async def get_database_info(database_path: Optional[str] = None,
                            extra_database_path: Optional[str] = None,
                            custom_database_path: Optional[str] = None) -> str:
    """Return database paths and signature counts as DiE's plain-text report."""
    try:
        options = database_options(database_path, extra_database_path, custom_database_path)
    except (ValueError, OSError) as error:
        return f'Error: {error}'
    return await asyncio.to_thread(run_die_command, None, ['--showdatabase'] + options)


def scan_directory(directory, recursive, filename_pattern, max_files, timeout_seconds, options):
    """Traverse and scan incrementally, limiting time, files, entries, and output."""
    deadline = time.monotonic() + timeout_seconds
    results, errors = [], []
    pending = [directory]
    visited = 0
    output_size = 0
    stopped_reason = None
    while pending and stopped_reason is None:
        if time.monotonic() >= deadline:
            stopped_reason = 'timeout'
            break
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if time.monotonic() >= deadline:
                        stopped_reason = 'timeout'
                        break
                    visited += 1
                    if visited > 10000:
                        stopped_reason = 'entry_limit'
                        break
                    try:
                        attributes = getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
                        if entry.is_symlink() or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if recursive:
                                pending.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False) or not fnmatch.fnmatch(entry.name, filename_pattern):
                            continue
                    except OSError as error:
                        errors.append({'path': entry.path, 'error': str(error)})
                        continue
                    if len(results) >= max_files:
                        stopped_reason = 'file_limit'
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        stopped_reason = 'timeout'
                        break
                    output = run_die_command(entry.path, options, timeout=min(120, remaining))
                    item = {'file_path': entry.path}
                    if output.startswith('Error:') or output.startswith('Error executing DIE'):
                        item['error'] = output[:10000]
                    else:
                        try:
                            item['result'] = json.loads(output)
                        except json.JSONDecodeError:
                            item['output'] = output
                    encoded_size = len(json.dumps(item))
                    if output_size + encoded_size > 990000:
                        results.append({'file_path': entry.path, 'error': 'Result omitted: batch output limit exceeded.'})
                        stopped_reason = 'output_limit'
                        break
                    output_size += encoded_size
                    results.append(item)
                    if time.monotonic() >= deadline:
                        stopped_reason = 'timeout'
                        break
        except OSError as error:
            errors.append({'path': current, 'error': str(error)})
    return json.dumps({'directory': directory, 'recursive': recursive, 'scanned_files': len(results),
                       'failed_files': sum('error' in item for item in results),
                       'complete': stopped_reason is None and not errors,
                       'stopped_reason': stopped_reason, 'results': results, 'traversal_errors': errors}, ensure_ascii=False)


@mcp.tool()
async def analyze_directory(directory_path: str, recursive: bool = False, filename_pattern: str = '*',
                            max_files: int = 20, timeout_seconds: int = 60,
                            deep_scan: bool = False, heuristic_scan: bool = False,
                            aggressive_scan: bool = False, entropy: bool = False,
                            verbose: bool = False, all_types: bool = False,
                            database_path: Optional[str] = None, extra_database_path: Optional[str] = None,
                            custom_database_path: Optional[str] = None) -> str:
    """Return a JSON batch of file scans, optionally descending into subdirectories.

    filename_pattern matches basenames (e.g. *.exe). max_files is 1..100;
    timeout_seconds is 1..300 for the whole batch. Traversal is limited to
    10,000 entries and results to 1,000,000 characters. Links are skipped.
    entropy=True returns entropy reports for the files instead of detections.
    complete/stopped_reason report traversal limits; each result may contain an error.
    """
    if not os.path.isdir(directory_path):
        return f"Error: Directory not found at path '{directory_path}'"
    if not 1 <= max_files <= 100 or not 1 <= timeout_seconds <= 300:
        return 'Error: max_files must be 1..100 and timeout_seconds must be 1..300.'
    if not filename_pattern or '/' in filename_pattern or '\\' in filename_pattern:
        return 'Error: filename_pattern must be a basename pattern, such as *.exe.'
    try:
        options = scan_options(deep_scan=deep_scan, entropy=entropy, verbose=verbose,
                               heuristic_scan=heuristic_scan, aggressive_scan=aggressive_scan,
                               all_types=all_types, database_path=database_path,
                               extra_database_path=extra_database_path, custom_database_path=custom_database_path)
        directory = str(Path(directory_path).resolve())
    except (ValueError, OSError) as error:
        return f'Error: {error}'
    return await asyncio.to_thread(scan_directory, directory, recursive, filename_pattern,
                                   max_files, timeout_seconds, options)


def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    sse = SseServerTransport('/messages/')

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
            await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

    return Starlette(debug=debug, routes=[Route('/sse', endpoint=handle_sse),
                                         Mount('/messages/', app=sse.handle_post_message)])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Run DIE MCP server with configurable transport')
    parser.add_argument('--transport', choices=['stdio', 'sse'], default='stdio', help='Transport mode (stdio or sse)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (for SSE mode)')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on (for SSE mode)')
    parser.add_argument('--die-path', help='Path to the DIE command-line executable (diec.exe)')
    args = parser.parse_args()
    if args.die_path:
        DIE_EXECUTABLE = args.die_path
    if args.transport == 'stdio':
        mcp.run(transport='stdio')
    else:
        uvicorn.run(create_starlette_app(mcp._mcp_server, debug=True), host=args.host, port=args.port)
