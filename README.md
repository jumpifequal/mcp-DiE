<p align="center">
  <img src="assets/logo.png" alt="DiE MCP logo" width="280">
</p>

# DiE (Detect It Easy) MCP Server

**DiE MCP gives Claude and Codex a local binary-triage service powered by [Detect It Easy](https://github.com/horsicq/Detect-It-Easy).** An assistant can identify a file's format and architecture, inspect compiler and packer detections, obtain hashes and entropy, and scan a directory through ten MCP tools. Analysis runs through the installed `diec` executable without launching the file being examined; reports are returned to the connected MCP client.

It is useful at the start of reverse engineering, malware triage, and software inventory: establish what a file is, collect identification evidence, and decide which files need deeper investigation. Dedicated reports, selectable signature databases, heuristic scan modes, and bounded batch scans support repeatable workflows. A Windows setup wizard and desktop console provide configuration, client registration, and diagnostics for Claude Desktop, Claude Code, and Codex.

### How it compares

| MCP project or category                                                     | Focus                                                                              | Where DiE MCP fits                                                                                                                                                             |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [D.I.E-MCP](https://github.com/lazy-importer/D.I.E-MCP)                     | Documents three tools for single-file analysis and special-information queries     | Ten tools covering identification, metadata, hashes, entropy, format checks, databases, version information, and bounded directory scans, with graphical setup and diagnostics |
| [Forensics Utils MCP](https://github.com/jus1-c/forensics-utils-mcp-server) | Combines DiE with VirusTotal, Binwalk, browser artifacts, and other forensic tools | A focused DiE integration using an existing local installation, with no reputation-service API key required                                                                    |
| [IDA Fusion MCP](https://github.com/andsopwn/ida-fusion-mcp)                | Decompilation, cross-references, patching, and debugger tooling                    | File identification and triage that can guide subsequent work in a disassembler or debugger                                                                                    |

DiE findings are identification evidence. Packer detections and high entropy can guide investigation; they do not establish whether a file is malicious. This server provides static inspection, rather than malware verdicts or a replacement for deeper reverse engineering.

## Quick start on Windows

1. Install **Python 3.11 or newer**, including Tkinter, and Detect It Easy with the `diec` command-line features described below (DiE 3.21 or newer).
2. Double-click **`setup-wizard.bat`** in the project root.
3. Follow the graphical wizard:
   - **Executable paths:** choose Python, `diec.exe`, and the MCP server name.
   - **Check the installation:** MCP checks run automatically. If dependencies are missing, click **Install dependencies**, then continue when checks pass.
   - **Choose your clients:** select Claude Desktop, Claude Code, Codex, or any combination. Select none to save settings only.
   - **Review and apply:** review the destination files and generated entries, then click **Apply**.
   - **Setup complete:** inspect the results and click **Finish**, or open the DiE MCP console.
4. Restart the configured clients to load the server.

Use **Back** to revisit a step. Cancel before **Apply** leaves settings and client registrations unchanged. Dependency installation, if selected, modifies the chosen Python environment.

The default DiE executable is:

```text
C:\Program Files\DiE\diec.exe
```

## Project layout

```text
mcp-DiE/
├── assets/
│   ├── logo.png              Project logo
│   └── social-preview.jpg    Repository social preview
├── .github/
│   └── workflows/
│       └── tests.yml         Automated Windows tests
├── setup-wizard.bat          Graphical setup launcher
├── console.bat               Desktop console launcher
├── scripts/
│   ├── setup_wizard.py       Graphical Next/Back/Finish wizard
│   ├── die_mcp_console.py    Desktop configuration and diagnostics
│   ├── configure.py          Shared settings, registration, and terminal setup
│   └── die_server.py         MCP server
├── tests/
│   ├── test_configuration.py
│   ├── test_die_tools.py
│   └── test_native_mcp.py
├── requirements.txt
├── README.md
└── LICENSE
```

Run the commands below from the project root.

## Desktop console

Double-click **`console.bat`** to open the graphical console.

- **Configuration:** browse for executables, change the server name and local SSE host/port, save settings, and check or install dependencies.
- **Clients:** select a client, refresh or copy its registration preview, and click **Write / update entry** to register the server with a backup.
- **Diagnostics & server:** run the MCP self-test, test DiE on a selected file, or start/stop an optional local SSE server.
- **Console log:** inspect results and errors, clear the view, or save the log.

Selected files are passed to DiE for static analysis.

## Settings and client registration

The setup wizard and console save configuration in `die-mcp-settings.json` in the **project root**. Terminal setup uses the same file.

The launchers prefer `.venv\Scripts\pythonw.exe` when present; otherwise they launch `pythonw` from PATH. For a new settings file, the interpreter picker defaults to the project virtual environment when available. Saved interpreter settings take precedence.

An optional isolated environment can be created before opening the wizard:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Registrations use stdio and absolute paths to the chosen Python interpreter, `scripts/die_server.py`, and `diec.exe`. Each client launches its own MCP process.

| Client         | Configuration destination                                         |
| -------------- | ----------------------------------------------------------------- |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json`                     |
| Claude Code    | `%USERPROFILE%\.claude.json` (user scope)                         |
| Codex          | `%CODEX_HOME%\config.toml`, or `%USERPROFILE%\.codex\config.toml` |

Registration preserves other settings and server entries. Existing configuration files receive unique timestamped `.bak` copies before replacement. Invalid configuration files are rejected. Codex updates preserve unrelated TOML text and verify that unrelated settings retain the same meaning. Unusual layouts, such as inline `mcp_servers` tables, are refused; use the preview to edit those manually.

After changing executable paths or moving the project, save settings and update the selected client registrations again. Changing the server name creates a new entry and leaves the old entry in place. Restore a backup by copying it over the original configuration with the affected client closed.

## Optional command-line usage

To configure the server using terminal prompts:

```powershell
python scripts/configure.py
```

To run the server directly:

```powershell
python scripts/die_server.py --die-path "C:\Program Files\DiE\diec.exe" --transport stdio
```

| Option                    | Description                                                               |
| ------------------------- | ------------------------------------------------------------------------- |
| `--transport {stdio,sse}` | Default: `stdio`                                                          |
| `--die-path PATH`         | DiE executable; overrides `DIE_EXECUTABLE` and the installed-path default |
| `--host HOST`             | SSE bind address; direct server default: `0.0.0.0`                        |
| `--port PORT`             | SSE port; default: `8080`                                                 |

The console's SSE controls accept loopback hosts only and default to `127.0.0.1`. This optional server uses `http://host:port/sse` and is separate from the stdio client registrations. The server has no network authentication. Closing the console terminates the SSE process it launched.

## MCP tools

| Tool                     | Purpose                                                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `analyze_file`           | Detect format, compiler, linker, packer, and protection; select scan modes, output format, and signature databases |
| `analyze_directory`      | Scan matching files in a directory, optionally including subdirectories, with batch limits                         |
| `get_file_info`          | File format, architecture, OS, size, and MIME type                                                                 |
| `get_file_hashes`        | DiE-supported hashes, including MD5, SHA-256, and SHA-512                                                          |
| `get_file_entropy`       | File entropy                                                                                                       |
| `check_file_format`      | DiE format-check results                                                                                           |
| `show_special_info`      | A named structure, such as `Info`, `Hash`, `Hash#MD5`, `Entropy`, or `Check format`                                |
| `list_available_methods` | Available structures for a file                                                                                    |
| `get_database_info`      | Database paths and signature counts                                                                                |
| `get_die_version`        | Installed DiE command-line version                                                                                 |

File tools accept `file_path`. `show_special_info` also requires `method`, the structure name returned by `list_available_methods`. Reports use DiE's JSON output; structure discovery, database information, and version information return plain text. Empty format-check results are returned as supplied by DiE. Unknown or unsupported structures can return `{"data": ""}`. On DiE 3.21, an empty file's hash structure contains empty values. These are native DiE results.

### File analysis options

`analyze_file` accepts these optional arguments:

| Argument               | Default | Behavior                                                                |
| ---------------------- | ------- | ----------------------------------------------------------------------- |
| `json_output`          | `true`  | JSON output; `false` selects plain text                                 |
| `output_format`        | unset   | Override `json_output` with `json`, `xml`, `csv`, `tsv`, or `plaintext` |
| `deep_scan`            | `false` | Deep scanning                                                           |
| `heuristic_scan`       | `false` | Heuristic detection                                                     |
| `aggressive_scan`      | `false` | Aggressive scanning                                                     |
| `entropy`              | `false` | Select the detailed entropy report instead of file detections |
| `verbose`              | `false` | Detailed output                                                         |
| `all_types`            | `false` | Scan all file types                                                     |
| `profiling`            | `false` | Profile signatures                                                      |
| `messages`             | `false` | Include scan messages and warnings                                      |
| `hide_unknown`         | `false` | Hide unknown file types                                                 |
| `database_path`        | unset   | Main signature database directory                                       |
| `extra_database_path`  | unset   | Extra signature database directory                                      |
| `custom_database_path` | unset   | Custom signature database directory                                     |

For an entropy report with per-section values, use `analyze_file` with `entropy: true`. DiE returns `total`, `status`, and `records` for supported file types. Use `get_file_entropy` for the whole-file entropy structure.

`messages: true` preserves native scan messages, which can appear before the report and make JSON or XML output unsuitable for direct parsing. Leave `messages` disabled when machine-readable output is required.

Database directories are optional per-call overrides, supported by `analyze_file`, `analyze_directory`, and `get_database_info`. They must exist and do not change saved settings.

Example `analyze_file` arguments:

```json
{
  "file_path": "C:\\Windows\\System32\\notepad.exe",
  "heuristic_scan": true,
  "deep_scan": true
}
```

### Directory analysis

`analyze_directory` requires `directory_path`. It returns a JSON object containing per-file results, `scanned_files`, `failed_files`, `complete`, `stopped_reason`, and `traversal_errors`.

| Argument           | Default | Behavior                                      |
| ------------------ | ------- | --------------------------------------------- |
| `recursive`        | `false` | Include subdirectories                        |
| `filename_pattern` | `*`     | Match file basenames, such as `*.exe`         |
| `max_files`        | `20`    | File limit, from 1 to 100                     |
| `timeout_seconds`  | `60`    | Whole-batch time limit, from 1 to 300 seconds |

Directory analysis also accepts `deep_scan`, `heuristic_scan`, `aggressive_scan`, `entropy`, `verbose`, `all_types`, and the three database directory arguments. Setting `entropy` to `true` selects per-file entropy reports instead of detection reports. Files are scanned individually with JSON output. Symbolic links and directory junctions are skipped. Traversal is limited to 10,000 entries and per-file result storage to approximately 1,000,000 characters. Files are processed in filesystem traversal order.

`complete` reports whether traversal finished without a limit or traversal error; it does not imply every file scan succeeded. Check `failed_files` and each result's `error`. `stopped_reason` identifies `file_limit`, `timeout`, `entry_limit`, or `output_limit`; it is `null` when no limit stopped the scan. An oversized file result is replaced by an error entry.

Example `analyze_directory` arguments:

```json
{
  "directory_path": "C:\\Samples",
  "recursive": true,
  "filename_pattern": "*.exe",
  "max_files": 20,
  "timeout_seconds": 60,
  "heuristic_scan": true
}
```

## Verification and troubleshooting

The automated tests verify client configuration preservation, supported CLI arguments, MCP tool behavior, and directory scan limits. The default suite uses temporary files and mocked native calls, so it does not require a DiE installation or modify client settings. Optional native integration tests exercise all ten tools through stdio and loopback SSE MCP sessions and compares reports with direct CLI calls. They are not required to run the MCP server.

Install the project dependencies, then run the tests from the project root:

```powershell
python -m unittest discover -s tests -v
```

To include the native integration test in PowerShell, set the installed executable path first:

```powershell
$env:DIE_TEST_EXECUTABLE = 'C:\Program Files\DiE\diec.exe'
python -m unittest discover -s tests -v
```

The native test scans DiE itself and temporary empty, text, truncated executable, and ZIP fixtures. It checks scan flags, output formats, structure reports, database overrides, directory results, hashes, and invalid inputs. Temporary fixtures are removed after the test. Without `DIE_TEST_EXECUTABLE`, the native tests are skipped.

To check the running MCP server with the configured interpreter:

```powershell
python scripts/configure.py --self-test
```

The MCP self-test initializes the server and checks that all ten tools are available. It does not prove that the native DiE executable can scan files. Use **Test DiE on a file** in the console for that check.

Diagnostics run off the GUI thread with bounded timeouts. Dependency installation can take up to five minutes. Individual server operations have a 120-second timeout; directory scans also apply their whole-batch time limit. The console's direct DiE diagnostic has a 60-second timeout.

If a double-click launcher does not open a window, run its Python file from a terminal to see startup errors:

```powershell
python scripts/setup_wizard.py
python scripts/die_mcp_console.py
```

Client formats follow the official [Codex MCP documentation](https://developers.openai.com/codex/mcp/), [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp), and [Claude Desktop local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers).
