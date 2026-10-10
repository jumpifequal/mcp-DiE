"""Graphical, step-by-step setup for DiE MCP."""
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import configure as config


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('DiE MCP setup wizard')
        self.geometry('880x650')
        self.minsize(760, 580)
        self.configure(bg='#12161c')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background='#12161c', foreground='#d7dde5', font=('Segoe UI', 10))
        style.configure('TEntry', fieldbackground='#1a2029', foreground='#d7dde5')
        style.configure('TButton', background='#232b36', padding=(12, 7))
        style.map('TButton', background=[('active', '#3ba99c')])
        self.step = 0
        self.busy = False
        self.checked = False
        self.applied = False
        self.events = queue.Queue()
        self.pending = []
        try:
            values = config.load_settings()
        except (ValueError, OSError) as error:
            messagebox.showwarning('Saved settings', f'{error}\nStarting with defaults.', parent=self)
            values = config.defaults()
        self.values = {key: tk.StringVar(value=str(value)) for key, value in values.items()}
        self.selected = {client: tk.BooleanVar(value=True) for client in config.CLIENTS}
        self.heading = ttk.Label(self, font=('Segoe UI', 20, 'bold'))
        self.heading.pack(anchor='w', padx=24, pady=(20, 6))
        self.description = ttk.Label(self, wraplength=810)
        self.description.pack(anchor='w', padx=24, pady=(0, 18))
        self.body = ttk.Frame(self, padding=(24, 0))
        self.body.pack(fill='both', expand=True)
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, wraplength=810).pack(anchor='w', padx=24, pady=12)
        navigation = ttk.Frame(self, padding=(24, 8, 24, 20))
        navigation.pack(fill='x')
        self.back = ttk.Button(navigation, text='Back', command=self.go_back)
        self.back.pack(side='left')
        self.next = ttk.Button(navigation, text='Next', command=self.advance)
        self.next.pack(side='right')
        self.cancel = ttk.Button(navigation, text='Cancel', command=self.close)
        self.cancel.pack(side='right', padx=10)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.show_step()
        self.after(100, self.poll)

    def current(self):
        return config.validate({key: var.get().strip() for key, var in self.values.items()})

    def show_step(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.status.set('')
        titles = ['Executable paths', 'Check the installation', 'Choose your clients', 'Review and apply', 'Setup complete']
        descriptions = [
            'Select Python and Detect It Easy. Review the executable paths before continuing.',
            'Check Python dependencies and initialize the MCP server. Install dependencies here if they are missing.',
            'Choose which clients should receive a local DiE MCP registration.',
            'Review the entries below. Apply saves settings and updates the selected clients, backing up existing files.',
            'Restart the configured clients to load DiE MCP. You can open the desktop console for diagnostics and settings.',
        ]
        self.heading.configure(text=f'{self.step + 1} / 5 — {titles[self.step]}')
        self.description.configure(text=descriptions[self.step])
        self.back.configure(state='normal' if 0 < self.step < 4 else 'disabled')
        self.next.configure(text='Apply' if self.step == 3 else 'Finish' if self.step == 4 else 'Next', state='normal')
        self.cancel.configure(state='disabled' if self.step == 4 else 'normal')
        if self.step == 0:
            self.body.columnconfigure(1, weight=1)
            for row, (key, label) in enumerate([('python', 'Python executable'), ('die_path', 'DiE executable'), ('name', 'MCP server name')]):
                ttk.Label(self.body, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=10)
                ttk.Entry(self.body, textvariable=self.values[key], width=60).grid(row=row, column=1, sticky='ew', pady=10)
                if key != 'name':
                    ttk.Button(self.body, text='Browse…', command=lambda k=key: self.browse(k)).grid(row=row, column=2, padx=(10, 0))
            ttk.Label(self.body, text='Python 3.11 or newer is required.\nSettings are saved only when you click Apply.', wraplength=750).grid(row=3, column=0, columnspan=3, sticky='w', pady=20)
        elif self.step == 1:
            buttons = ttk.Frame(self.body)
            buttons.pack(anchor='w', pady=(0, 12))
            self.check_button = ttk.Button(buttons, text='Run checks', command=self.check)
            self.check_button.pack(side='left')
            self.install_button = ttk.Button(buttons, text='Install dependencies', command=self.install)
            self.install_button.pack(side='left', padx=10)
            self.make_output()
            self.output_text('Click Run checks to verify this interpreter and server.\nA successful MCP check does not guarantee that diec.exe can scan files.\nUse the console’s DiE file test after setup.')
            self.next.configure(state='normal' if self.checked else 'disabled')
        elif self.step == 2:
            for client in config.CLIENTS:
                ttk.Checkbutton(self.body, text=client + (' (user scope)' if client == 'Claude Code' else ''), variable=self.selected[client]).pack(anchor='w', pady=10)
                ttk.Label(self.body, text=str(config.client_path(client)), wraplength=760).pack(anchor='w', padx=24)
            ttk.Label(self.body, text='Select no clients to save settings only.').pack(anchor='w', pady=20)
        elif self.step == 3:
            self.make_output()
            values = self.current()
            text = f'Settings: {config.SETTINGS}\n\n'
            for client in config.CLIENTS:
                if self.selected[client].get():
                    text += f'{client}\n{config.client_path(client)}\n{config.preview(client, values)}\n'
            self.output_text(text)
        else:
            self.make_output()
            self.output_text('\n\n'.join(self.pending))
            ttk.Button(self.body, text='Open DiE MCP console', command=self.open_console).pack(anchor='w', pady=12)

    def make_output(self):
        frame = ttk.Frame(self.body)
        frame.pack(fill='both', expand=True)
        self.output = tk.Text(frame, bg='#0d1117', fg='#d7dde5', font=('Consolas', 10), wrap='word', relief='flat', state='disabled')
        scroll = ttk.Scrollbar(frame, command=self.output.yview)
        scroll.pack(side='right', fill='y')
        self.output.configure(yscrollcommand=scroll.set)
        self.output.pack(fill='both', expand=True)

    def output_text(self, text):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('end', text)
        self.output.configure(state='disabled')

    def browse(self, key):
        path = filedialog.askopenfilename(parent=self, title='Select executable', filetypes=[('Executables', '*.exe'), ('All files', '*')])
        if path:
            self.values[key].set(path)

    def go_back(self):
        if not self.busy:
            self.step -= 1
            self.show_step()

    def advance(self):
        if self.busy:
            return
        try:
            if self.step == 4:
                self.destroy()
                return
            if self.step == 0:
                self.current()
                self.checked = False
            elif self.step == 1 and not self.checked:
                return
            elif self.step == 3:
                self.apply()
                return
            self.step += 1
            self.show_step()
            if self.step == 1 and not self.checked:
                self.after(50, self.check)
        except (ValueError, OSError) as error:
            messagebox.showerror('Setup', str(error), parent=self)

    def run_job(self, task, action):
        self.busy = True
        self.back.configure(state='disabled')
        self.next.configure(state='disabled')
        self.cancel.configure(state='disabled')
        if self.step == 1:
            self.check_button.configure(state='disabled')
            self.install_button.configure(state='disabled')
        self.status.set('Working…')
        def worker():
            try:
                self.events.put((action, task(), None))
            except Exception as error:
                self.events.put((action, None, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def check(self):
        values = self.current()
        self.checked = False
        self.run_job(lambda: config.self_test(values), 'check')

    def install(self):
        values = self.current()
        if messagebox.askyesno('Install dependencies', f'Install requirements.txt into\n{values["python"]}?', parent=self):
            self.checked = False
            def task():
                result = config.install_dependencies(values)
                return result + '\n' + config.self_test(values)
            self.run_job(task, 'check')

    def apply(self):
        values = self.current()
        clients = [client for client in config.CLIENTS if self.selected[client].get()]
        def task():
            results = []
            config.save_settings(values)
            results.append(f'Settings saved: {config.SETTINGS}')
            for client in clients:
                try:
                    results.append(config.register(client, values))
                except Exception as error:
                    results.append(f'FAILED — {client}: {error}')
            return results
        self.run_job(task, 'apply')

    def poll(self):
        try:
            action, result, error = self.events.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        self.busy = False
        self.cancel.configure(state='normal')
        self.back.configure(state='normal')
        if error:
            self.output_text(error)
            self.status.set('Check failed. Correct the settings or install the dependencies, then try again.' if action == 'check' else 'Apply failed. See details above.')
            self.next.configure(state='disabled' if action == 'check' else 'normal')
        elif action == 'check':
            self.checked = True
            self.output_text(result)
            self.status.set('MCP checks passed. Click Next.')
            self.next.configure(state='normal')
        else:
            self.pending = result
            self.applied = True
            self.step = 4
            self.show_step()
            if any(item.startswith('FAILED') for item in result):
                self.heading.configure(text='5 / 5 — Setup completed with errors')
        if self.step == 1:
            self.check_button.configure(state='normal')
            self.install_button.configure(state='normal')
        self.after(100, self.poll)

    def open_console(self):
        subprocess.Popen([self.current()['python'], str(config.SCRIPTS / 'die_mcp_console.py')], creationflags=config.FLAGS)

    def close(self):
        if self.busy:
            messagebox.showinfo('Setup in progress', 'Wait for the current operation to finish.', parent=self)
        elif self.applied or messagebox.askyesno('Cancel setup', 'Close setup without applying changes?', parent=self):
            self.destroy()


if __name__ == '__main__':
    SetupWizard().mainloop()
