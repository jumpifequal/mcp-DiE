"""Desktop configuration and diagnostics console for DiE MCP."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import configure as config

BG, PANEL, FG, MUTED, ACCENT = '#12161c', '#1a2029', '#d7dde5', '#8793a3', '#3ba99c'


class Console(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('DiE MCP console')
        self.geometry('1000x780')
        self.minsize(820, 650)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.process = None
        self.busy = False
        self.buttons = []
        try:
            settings = config.load_settings()
        except (ValueError, OSError) as error:
            messagebox.showerror('Settings error', str(error), parent=self)
            settings = config.defaults()
        self.values = {k: tk.StringVar(value=str(v)) for k, v in settings.items()}
        self.client = tk.StringVar(value='Claude Desktop')
        self.status = tk.StringVar(value='Ready — stdio servers are launched by Claude or Codex')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Segoe UI', 10))
        style.configure('TNotebook.Tab', padding=(18, 8))
        style.map('TNotebook.Tab', background=[('selected', PANEL)])
        style.configure('TEntry', fieldbackground=PANEL, foreground=FG)
        style.configure('TCombobox', fieldbackground=PANEL, foreground=FG)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', FG)])
        style.configure('TButton', background=PANEL, padding=(10, 6))
        style.map('TButton', background=[('active', ACCENT)])
        ttk.Label(self, text='DiE MCP CONSOLE', font=('Segoe UI', 20, 'bold')).pack(anchor='w', padx=20, pady=(16, 4))
        ttk.Label(self, text='Configuration • Client registration • Diagnostics', foreground=MUTED).pack(anchor='w', padx=20, pady=(0, 12))
        notebook = ttk.Notebook(self)
        notebook.pack(fill='x', padx=18)
        setup = ttk.Frame(notebook, padding=16)
        clients = ttk.Frame(notebook, padding=16)
        diagnostics = ttk.Frame(notebook, padding=16)
        notebook.add(setup, text='Configuration')
        notebook.add(clients, text='Clients')
        notebook.add(diagnostics, text='Diagnostics & server')
        setup.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate([('python', 'Python executable'), ('die_path', 'DiE executable'),
                                            ('name', 'Server name'), ('host', 'SSE host'), ('port', 'SSE port')]):
            ttk.Label(setup, text=label).grid(row=row, column=0, sticky='w', padx=(0, 14), pady=5)
            ttk.Entry(setup, textvariable=self.values[key], width=65).grid(row=row, column=1, sticky='ew', pady=5)
            if key in ('python', 'die_path'):
                ttk.Button(setup, text='Browse…', command=lambda k=key: self.browse(k)).grid(row=row, column=2, padx=(8, 0))
        bar = ttk.Frame(setup)
        bar.grid(row=5, column=0, columnspan=3, sticky='w', pady=12)
        self.button(bar, 'Save settings', self.save)
        self.button(bar, 'Check dependencies', lambda: self.job(config.dependency_check))
        self.button(bar, 'Install dependencies', self.install)
        ttk.Label(setup, text=f'Settings: {config.SETTINGS}', foreground=MUTED).grid(row=6, column=0, columnspan=3, sticky='w')
        ttk.Label(clients, text='Client (stdio)').pack(anchor='w')
        combo = ttk.Combobox(clients, textvariable=self.client, values=config.CLIENTS, state='readonly')
        combo.pack(anchor='w', pady=6)
        combo.bind('<<ComboboxSelected>>', lambda _: self.refresh_preview())
        self.destination = ttk.Label(clients, foreground=MUTED)
        self.destination.pack(anchor='w', pady=4)
        self.preview = self.text(clients, height=7)
        bar = ttk.Frame(clients)
        bar.pack(anchor='w', pady=(10, 0))
        self.button(bar, 'Refresh preview', self.refresh_preview)
        self.button(bar, 'Copy entry', self.copy_entry)
        self.button(bar, 'Write / update entry', self.register)
        self.button(bar, 'Open config folder', self.open_folder)
        ttk.Label(diagnostics, text='Stdio: clients own the process. Test the MCP handshake and available tool registrations.').pack(anchor='w', pady=4)
        bar = ttk.Frame(diagnostics)
        bar.pack(anchor='w', pady=8)
        self.button(bar, 'MCP self-test', lambda: self.job(config.self_test))
        self.button(bar, 'Test DiE on a file…', self.scan)
        ttk.Label(diagnostics, text='Optional local SSE server: http://host:port/sse (registrations above use stdio).').pack(anchor='w', pady=4)
        bar = ttk.Frame(diagnostics)
        bar.pack(anchor='w', pady=8)
        self.button(bar, 'Start SSE', self.start_server)
        self.stop_button = ttk.Button(bar, text='Stop SSE', command=self.stop_server, state='disabled')
        self.stop_button.pack(side='left', padx=(0, 8))
        self.server_status = ttk.Label(diagnostics, text='SSE stopped', foreground=MUTED)
        self.server_status.pack(anchor='w')
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=18, pady=(12, 5))
        ttk.Label(bar, text='CONSOLE', font=('Segoe UI', 10, 'bold')).pack(side='left')
        ttk.Button(bar, text='Clear', command=lambda: self.replace(self.log, '')).pack(side='right')
        ttk.Button(bar, text='Save log…', command=self.save_log).pack(side='right', padx=8)
        self.log = self.text(self, height=12, expand=True)
        self.log.tag_configure('error', foreground='#ef6b6b')
        self.log.tag_configure('ok', foreground='#4cc38a')
        ttk.Label(self, textvariable=self.status, foreground=MUTED).pack(anchor='w', padx=20, pady=10)
        self.refresh_preview()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def text(self, parent, height, expand=False):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=expand, padx=18 if parent is self else 0)
        widget = tk.Text(frame, height=height, bg='#0d1117', fg=FG, insertbackground=FG,
                         font=('Consolas', 10), wrap='word', relief='flat', state='disabled')
        scrollbar = ttk.Scrollbar(frame, command=widget.yview)
        scrollbar.pack(side='right', fill='y')
        widget.configure(yscrollcommand=scrollbar.set)
        widget.pack(fill='both', expand=True)
        return widget

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=label, command=lambda: self.safe(command))
        button.pack(side='left', padx=(0, 8))
        self.buttons.append(button)
        return button

    def safe(self, function):
        try:
            function()
        except Exception as error:
            self.append(str(error), 'error')
            messagebox.showerror('DiE MCP', str(error), parent=self)

    def current(self):
        return config.validate({k: v.get().strip() for k, v in self.values.items()})

    def browse(self, key):
        path = filedialog.askopenfilename(title='Select executable', filetypes=[('Executables', '*.exe'), ('All files', '*')])
        if path:
            self.values[key].set(path)

    def replace(self, widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('end', text)
        widget.configure(state='disabled')

    def append(self, message, tag='ok'):
        self.log.configure(state='normal')
        self.log.insert('end', message.rstrip() + '\n', tag)
        if int(self.log.index('end-1c').split('.')[0]) > 12000:
            self.log.delete('1.0', '2000.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def save(self):
        config.save_settings(self.current())
        self.append(f'Settings saved: {config.SETTINGS}')
        self.refresh_preview()

    def refresh_preview(self):
        values = {k: v.get().strip() for k, v in self.values.items()}
        self.destination.configure(text=str(config.client_path(self.client.get())))
        self.replace(self.preview, config.preview(self.client.get(), values))

    def copy_entry(self):
        self.refresh_preview()
        self.clipboard_clear()
        self.clipboard_append(self.preview.get('1.0', 'end-1c'))
        self.append('Client entry copied.')

    def register(self):
        values = self.current()
        client = self.client.get()
        self.refresh_preview()
        if messagebox.askyesno('Register DiE MCP', f'Write the preview to\n{config.client_path(client)}?\n\nExisting settings are preserved and a backup is created.', parent=self):
            self.append(config.register(client, values))
            config.save_settings(values)
            self.append('Restart this client to load the updated registration.')

    def open_folder(self):
        import os
        path = config.client_path(self.client.get()).parent
        if not path.exists():
            raise ValueError(f'Folder does not exist yet: {path}')
        os.startfile(str(path))

    def job(self, function):
        if self.busy:
            raise ValueError('Wait for the current diagnostic or installation to finish.')
        values = self.current()
        self.busy = True
        self.status.set('Working…')
        for button in self.buttons:
            button.configure(state='disabled')
        def worker():
            try:
                self.events.put(('result', function(values)))
            except Exception as error:
                self.events.put(('error', str(error)))
            finally:
                self.events.put(('done', ''))
        threading.Thread(target=worker, daemon=True).start()

    def install(self):
        if messagebox.askyesno('Install dependencies', f'Install requirements.txt into\n{self.values["python"].get()}?', parent=self):
            self.job(config.install_dependencies)

    def scan(self):
        target = filedialog.askopenfilename(title='Select a file for static DiE analysis')
        if not target:
            return
        def run(values):
            result = subprocess.run([values['die_path'], '--json', target], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=60, creationflags=config.FLAGS)
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout or f'DiE exited with {result.returncode} (0x{result.returncode & 0xffffffff:08X}). Check the DiE installation.')
            return result.stdout or 'DiE returned no output.'
        self.job(run)

    def start_server(self):
        if self.process:
            raise ValueError('The console already owns an SSE process.')
        values = self.current()
        command = config.server_command(values, 'sse') + ['--host', values['host'], '--port', str(values['port'])]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace', creationflags=config.FLAGS)
        self.stop_button.configure(state='normal')
        self.server_status.configure(text=f'SSE process {self.process.pid} — http://{values["host"]}:{values["port"]}/sse')
        self.append('Starting local SSE server…')
        process = self.process
        def reader():
            try:
                for line in process.stdout:
                    self.events.put(('server', line))
            finally:
                process.stdout.close()
        threading.Thread(target=reader, daemon=True).start()

    def stop_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def poll(self):
        while True:
            try:
                kind, message = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'done':
                self.busy = False
                self.status.set('Ready')
                for button in self.buttons:
                    button.configure(state='normal')
            else:
                self.append(message, 'error' if kind == 'error' else 'ok')
        if self.process and self.process.poll() is not None:
            self.append(f'SSE process exited ({self.process.returncode}).')
            self.process = None
            self.stop_button.configure(state='disabled')
            self.server_status.configure(text='SSE stopped')
        self.after(100, self.poll)

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension='.log', filetypes=[('Log', '*.log')])
        if path:
            self.safe(lambda: Path(path).write_text(self.log.get('1.0', 'end-1c'), encoding='utf-8'))

    def close(self):
        self.stop_server()
        self.destroy()


if __name__ == '__main__':
    Console().mainloop()
