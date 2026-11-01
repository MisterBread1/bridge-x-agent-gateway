"""Native Tk operator console. The proxy lives in a background thread."""
import json
import locale
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from . import __version__
from .desktop_host import GatewayHost, save_connection
from .desktop_i18n import text
from .errors import BridgeError
from .paths import data_dir


class Desktop:
    columns = ("time", "scope", "method", "path", "http", "phase", "total_ms", "queue_ms", "upstream_ms")

    def __init__(self, root, settings, port=8787, host=None):
        self.root, self.settings = root, settings
        self.host = host or GatewayHost(settings, port)
        self.settings = getattr(self.host, "settings", settings)
        self.language = "ru" if (locale.getlocale()[0] or "").lower().startswith("ru") else "en"
        self.preferences = data_dir() / "desktop.json"
        try:
            preference = json.loads(self.preferences.read_text(encoding="utf-8"))
            if isinstance(preference, dict) and preference.get("language") in {"en", "ru"}: self.language = preference["language"]
        except (OSError, ValueError): pass
        self.labels = []; self.wrap_labels = []; self.jobs = queue.Queue(); self.job_pending = False; self.closed = False
        self.latest = {}; self.results = []; self.extra_config = {}; self.restart_port = None; self.note = ("", {}, None)
        self.rendered = {}; self.diagnostic_text = ""
        self.root.geometry("1120x720"); self.root.minsize(820, 520)
        style = ttk.Style(root)
        if os.name == "nt" and "vista" in style.theme_names(): style.theme_use("vista")
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 10))
        style.configure("TButton", padding=(10, 5)); style.configure("TNotebook.Tab", padding=(15, 8))
        outer = ttk.Frame(root, padding=16); outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer); top.pack(fill="x")
        ttk.Label(top, text="Bridge X", font=("Segoe UI", 20)).pack(side="left")
        ttk.Label(top, text=__version__, foreground="#666666", padding=(12, 0)).pack(side="left")
        self.lang = tk.StringVar(value=self.language.upper() if self.language == "en" else "RUS")
        self.lang.set("ENG" if self.language == "en" else "RUS")
        language = ttk.Combobox(top, textvariable=self.lang, values=("ENG", "RUS"), width=6, state="readonly")
        language.pack(side="right"); language.bind("<<ComboboxSelected>>", self.change_language)
        self.status = ttk.Label(outer, font=("Segoe UI", 11), wraplength=1000, justify="left"); self.status.pack(fill="x", pady=(8, 10))
        self.wrap_labels.append(self.status)
        tools = ttk.Frame(outer); tools.pack(fill="x", pady=(0, 12))
        self.start_button = self.button(tools, "start", self.start); self.start_button.pack(side="left")
        self.stop_button = self.button(tools, "stop", self.stop); self.stop_button.pack(side="left", padx=6)
        self.button(tools, "copy", self.copy_address).pack(side="left", padx=(8, 6))
        self.button(tools, "check", self.diagnose).pack(side="left", padx=6)
        self.button(tools, "export", self.export).pack(side="left", padx=6)
        self.address = tk.StringVar(value=f"http://127.0.0.1:{port}/v1")
        ttk.Entry(outer, textvariable=self.address, state="readonly", font=("Consolas", 10)).pack(fill="x", pady=(0, 12))
        self.notice = ttk.Label(outer, wraplength=1000); self.notice.pack(side="bottom", fill="x", pady=(3, 0))
        self.footer = ttk.Label(outer); self.footer.pack(side="bottom", fill="x", pady=(10, 0))
        self.notebook = ttk.Notebook(outer); self.notebook.pack(fill="both", expand=True)
        self.request_tab = ttk.Frame(self.notebook, padding=8)
        self.diagnostic_tab = ttk.Frame(self.notebook, padding=10)
        self.settings_tab = ttk.Frame(self.notebook, padding=16)
        for tab in (self.request_tab, self.diagnostic_tab, self.settings_tab): self.notebook.add(tab)
        filters = ttk.Frame(self.request_tab); filters.pack(fill="x", pady=(0, 8))
        self.label(filters, "filter").pack(side="left", padx=(0, 8))
        self.filter = ttk.Combobox(filters, width=20, state="readonly")
        self.filter.pack(side="left"); self.filter.bind("<<ComboboxSelected>>", lambda event: self.render_snapshot(self.latest))
        self.show_checks = tk.BooleanVar(value=False)
        self.checks_toggle = ttk.Checkbutton(filters, variable=self.show_checks, command=lambda: self.render_snapshot(self.latest))
        self.checks_toggle.pack(side="left", padx=16); self.labels.append((self.checks_toggle, "show_checks"))
        grid = ttk.Frame(self.request_tab); grid.pack(fill="both", expand=True)
        grid.rowconfigure(0, weight=1); grid.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(grid, columns=self.columns, show="headings", selectmode="browse")
        widths = (88, 88, 62, 220, 58, 170, 80, 80, 80)
        for column, width in zip(self.columns, widths): self.table.column(column, width=width, minwidth=50, stretch=column in {"path", "phase"})
        scroll = ttk.Scrollbar(grid, orient="vertical", command=self.table.yview)
        across = ttk.Scrollbar(grid, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        self.table.grid(row=0, column=0, sticky="nsew"); scroll.grid(row=0, column=1, sticky="ns"); across.grid(row=1, column=0, sticky="ew")
        self.table.tag_configure("failed", foreground="#a52323"); self.table.tag_configure("active", foreground="#6e570f")
        self.table.bind("<<TreeviewSelect>>", lambda event: self.render_detail())
        details = ttk.Frame(self.request_tab); details.pack(fill="x", pady=(8, 0))
        self.detail = tk.Text(details, height=5, wrap="word", font=("Segoe UI", 10), relief="flat", padx=8, pady=8, state="disabled")
        detail_scroll = ttk.Scrollbar(details, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set); detail_scroll.pack(side="right", fill="y"); self.detail.pack(fill="x")
        self.diagnostic = tk.Text(self.diagnostic_tab, wrap="word", font=("Consolas", 10), relief="flat", state="disabled")
        self.diagnostic.pack(fill="both", expand=True)
        self.build_settings()
        self.load_config(); self.translate()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Configure>", self.resize)
        root.after(80, self.start); root.after(200, self.refresh)

    def t(self, key, **values): return text(key, self.language, **values)

    def label(self, parent, key, **options):
        widget = ttk.Label(parent, text=self.t(key), **options); self.labels.append((widget, key))
        if "wraplength" in options: self.wrap_labels.append(widget)
        return widget

    def resize(self, event):
        if self.closed or event.widget is not self.root: return
        for widget in self.wrap_labels: widget.configure(wraplength=max(400, event.width - 80))
        self.notice.configure(wraplength=max(400, event.width - 40))

    def button(self, parent, key, command):
        widget = ttk.Button(parent, text=self.t(key), command=command); self.labels.append((widget, key)); return widget

    def build_settings(self):
        frame = self.settings_tab; frame.columnconfigure(1, weight=1)
        self.label(frame, "config_help", wraplength=850).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.fields = {}
        for row, (key, name) in enumerate((("runtime", "chat_url"), ("session", "marimo_session_id"), ("token", "marimo_server_token")), 1):
            self.label(frame, key).grid(row=row, column=0, sticky="w", padx=(0, 15), pady=7)
            value = self.fields[name] = tk.StringVar()
            ttk.Entry(frame, textvariable=value, show="•" if key == "token" else "").grid(row=row, column=1, sticky="ew", pady=7)
        buttons = ttk.Frame(frame); buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=12)
        self.button(buttons, "save", self.save).pack(side="left")
        self.button(buttons, "import", self.import_config).pack(side="left", padx=8)
        self.button(buttons, "check_molab", self.check_molab).pack(side="left")
        self.label(frame, "port").grid(row=5, column=0, sticky="w", pady=(20, 7))
        ports = ttk.Frame(frame); ports.grid(row=5, column=1, sticky="w", pady=(20, 7))
        self.port = tk.StringVar(value=str(self.host.port))
        ttk.Spinbox(ports, from_=1, to=65535, textvariable=self.port, width=8).pack(side="left")
        self.button(ports, "apply_port", self.apply_port).pack(side="left", padx=10)
        self.label(frame, "model").grid(row=6, column=0, sticky="w", pady=8)
        ttk.Label(frame, text="molab-glm", font=("Consolas", 11)).grid(row=6, column=1, sticky="w")
        self.label(frame, "compat", wraplength=850).grid(row=7, column=0, columnspan=2, sticky="w", pady=12)

    def change_language(self, event=None):
        self.language = "en" if self.lang.get() == "ENG" else "ru"
        try:
            self.preferences.parent.mkdir(parents=True, exist_ok=True)
            self.preferences.write_text(json.dumps({"language": self.language}), encoding="utf-8")
        except OSError: pass
        self.translate()

    def translate(self):
        self.root.title(self.t("title") + (" — " + self.t("test_instance") if self.settings.provider == "fake" else ""))
        selected = max(0, self.filter.current())
        self.filter.configure(values=[self.t(key) for key in ("all", "errors_only", "active_only")]); self.filter.current(selected)
        for widget, key in self.labels: widget.configure(text=self.t(key))
        for tab, key in ((self.request_tab, "requests"), (self.diagnostic_tab, "diagnostics"), (self.settings_tab, "settings")):
            self.notebook.tab(tab, text=self.t(key))
        for column in self.columns: self.table.heading(column, text=self.t(column))
        self.render_detail(); self.render_snapshot(self.latest); self.render_notice()

    def set_notice(self, key="", error=None, **values):
        self.note = (key, values, error); self.render_notice()

    def render_notice(self):
        key, values, error = self.note
        if error:
            message = self.t(error)
            self.notice.configure(text=(message if message != error else self.t("http_error")) + " (" + error + ")")
        else: self.notice.configure(text=self.t(key, **values) if key else "")

    @staticmethod
    def put(widget, value):
        widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("1.0", value); widget.configure(state="disabled")

    def duration(self, value):
        return "—" if value is None else f"{value / 1000:.2f} s" if value >= 1000 else f"{value} ms"

    def render_snapshot(self, snapshot):
        if not snapshot: return
        state = snapshot["state"]; status = self.t(state)
        status += "  ·  " + snapshot["provider"] + "  ·  " + snapshot["model"]
        if snapshot["provider"] == "molab" and state == "running":
            status += "  ·  " + self.t("molab_verified" if snapshot.get("connection", {}).get("verified") else "molab_unverified")
        if snapshot["error"]: status += " · " + self.t(snapshot["error"]) + " (" + snapshot["error"] + ")"
        elif snapshot["rate"].get("cooldown_remaining_seconds", 0): status += " · " + self.t("cooldown", seconds=snapshot["rate"]["cooldown_remaining_seconds"])
        self.status.configure(text=status, foreground="#a52323" if state == "error" else "#245a3e" if state == "running" else "#555555")
        self.address.set(f"http://127.0.0.1:{snapshot['port']}/v1")
        self.start_button.configure(state="normal" if state in {"stopped", "error"} else "disabled")
        self.stop_button.configure(state="normal" if state in {"starting", "running"} else "disabled")
        all_rows = snapshot["requests"]
        rows = [row for row in all_rows if (self.show_checks.get() or row["method"] != "GET")
                and (self.filter.current() != 1 or row["phase"] in {"failed", "cancelled"})
                and (self.filter.current() != 2 or row["active"])]
        known = {str(row["id"]) for row in rows}
        for iid in self.table.get_children():
            if iid not in known: self.table.delete(iid); self.rendered.pop(iid, None)
        for row in reversed(rows):
            values = (row["at"][11:19], self.t(row["scope"]), row["method"], row["path"], row["http"] or "…", self.t(row["phase"]),
                      self.duration(row["total_ms"]), self.duration(row["queue_ms"]), self.duration(row["upstream_ms"]))
            tag = "failed" if row["phase"] == "failed" else "active" if row["active"] else ""
            iid = str(row["id"])
            if self.rendered.get(iid) == (values, tag): continue
            if iid in self.rendered: self.table.item(iid, values=values, tags=(tag,))
            else: self.table.insert("", 0, iid=iid, values=values, tags=(tag,))
            self.rendered[iid] = (values, tag)
        self.footer.configure(text=self.t("counts", total=len(rows), active=sum(row["active"] for row in rows), errors=sum(row["phase"] == "failed" for row in rows)) if rows else self.t("no_matching" if all_rows else "empty"))
        logging = snapshot.get("logging", {})
        if logging.get("failed") or logging.get("dropped"):
            self.footer.configure(text=self.footer.cget("text") + " · " + self.t("log_warning", count=logging.get("dropped", 0)))
        self.render_detail()

    def render_detail(self):
        selection = self.table.selection()
        row = next((item for item in self.latest.get("requests", []) if selection and str(item["id"]) == selection[0]), None)
        if not row: self.put(self.detail, self.t("details")); return
        self.put(self.detail, f"#{row['id']}  {row['method']} {row['path']}  HTTP {row['http'] or '…'}  ·  {self.t(row['phase'])}\n"
                 f"{self.t('queue_ms')}: {self.duration(row['queue_ms'])}  |  Molab: {self.duration(row['upstream_ms'])}  |  {self.t('first_output')}: {self.duration(row['first_output_ms'])}\n"
                 f"{self.t('payload_size')}: {row.get('request_bytes', 0):,} / {row.get('response_bytes', 0):,} B\n"
                 f"{self.t('retries')}: {row['retries']}  |  {self.t('http_error')}: {row['error_code'] or self.t('no_error')}"
                 + (" — " + self.t(row['error_code']) if row['error_code'] in {"TOOL_SCHEMA_MISMATCH", "CONTEXT_BUDGET_EXCEEDED", "UPSTREAM_CONTEXT_LIMIT", "UPSTREAM_RATE_LIMIT", "MOLAB_QUEUE_TIMEOUT", "MOLAB_ACCESS_DENIED", "MOLAB_CONFIG_MISSING"} else ""))

    def refresh(self):
        if self.closed: return
        self.latest = self.host.snapshot(); self.render_snapshot(self.latest)
        while not self.jobs.empty():
            kind, result = self.jobs.get_nowait(); self.job_pending = False
            if kind == "error": self.set_notice(error=result)
            elif kind == "doctor": self.results = result["checks"]; self.set_notice()
            elif kind == "molab": self.set_notice("access_checked", mode=result["mode"])
        checks = "\n".join(f"{self.t(row['status'])}  {row['code']}: " + (self.t(row["code"]) if self.language == "ru" else row["recommendation"]) for row in self.results)
        events = "\n".join(f"{event['at']}  #{event['request']}  {self.t(event['phase'])}  {event['error_code'] or ''}" for event in self.latest["events"])
        diagnostic_text = self.t("local_checks") + "\n" + checks + "\n\n" + self.t("events") + "\n" + events
        if diagnostic_text != self.diagnostic_text:
            self.put(self.diagnostic, diagnostic_text); self.diagnostic_text = diagnostic_text
        if self.restart_port is not None and self.latest["state"] in {"stopped", "error"} and (self.host.thread is None or not self.host.thread.is_alive()):
            self.host.port = self.restart_port; self.restart_port = None; self.start()
        self.root.after(350, self.refresh)

    def start(self): self.host.start()

    def stop(self):
        if any(row["active"] for row in self.host.snapshot()["requests"]):
            if not messagebox.askyesno("Bridge X", self.t("confirm_stop"), parent=self.root): return False
        self.host.stop(); return True

    def job(self, kind, function):
        if self.job_pending: self.set_notice("busy"); return
        self.job_pending = True; self.set_notice("checking")
        def work():
            try: self.jobs.put((kind, function()))
            except BridgeError as error: self.jobs.put(("error", error.code))
            except Exception: self.jobs.put(("error", "INTERNAL_ERROR"))
        threading.Thread(target=work, daemon=True).start()

    def diagnose(self):
        from .doctor import inspect
        self.notebook.select(self.diagnostic_tab)
        def check():
            result = inspect(self.settings, self.host.port)
            if self.host.snapshot()["state"] == "running":
                for row in result["checks"]:
                    if row["code"] == "LOCAL_PORT":
                        row.update(status="PASS", recommendation="This window owns the running local proxy on the selected port.")
            return result
        self.job("doctor", check)

    def check_molab(self):
        from .molab_provider import read_molab_config
        from .molab_runtime import ensure_native_mode
        self.job("molab", lambda: ensure_native_mode(read_molab_config(self.settings.molab_config_path), configure=False))

    def load_config(self, filename=None):
        try:
            from .json_utils import loads
            value = loads(Path(filename or self.settings.molab_config_path).read_bytes())
            from .molab_provider import validate_molab_config
            validate_molab_config(value)
            for field, variable in self.fields.items(): variable.set(value.get(field, ""))
            self.extra_config = {key: value[key] for key in ("http_headers", "notebook_url") if key in value}
            self.set_notice("config_present")
        except FileNotFoundError:
            self.set_notice("offline" if self.settings.provider == "fake" else "config_missing")
        except BridgeError as error: self.set_notice(error=error.code)
        except (ValueError, UnicodeError): self.set_notice(error="MOLAB_CONFIG_INVALID")
        except OSError: self.set_notice(error="LOCAL_STORAGE_UNAVAILABLE")

    def import_config(self):
        name = filedialog.askopenfilename(parent=self.root, filetypes=[("Molab configuration", "*.json *.example"), ("All files", "*")])
        if name: self.load_config(name)

    def save(self):
        try:
            save_connection(self.settings, {**self.extra_config, **{name: variable.get().strip() for name, variable in self.fields.items()}})
            if self.host.app is not None:
                provider = self.host.app.state.provider
                if hasattr(provider, "live_verified"): provider.live_verified = False
            self.set_notice("config_saved")
        except BridgeError as error: self.set_notice(error=error.code)
        except OSError: self.set_notice(error="LOCAL_STORAGE_UNAVAILABLE")

    def apply_port(self):
        try:
            port = int(self.port.get()); assert 1 <= port <= 65535
        except (ValueError, AssertionError): self.set_notice(error="PORT_RANGE_1_65535"); return
        if self.stop(): self.restart_port = port

    def copy_address(self):
        try: self.root.clipboard_clear(); self.root.clipboard_append(self.address.get()); self.set_notice("copied")
        except tk.TclError: self.set_notice("clipboard_failed")

    def export(self):
        name = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json", initialfile="bridge-x-diagnostics.json", filetypes=[("JSON", "*.json")])
        if not name: return
        try:
            report = {"version": __version__, "requests": self.host.monitor.snapshot(), "checks": self.results,
                      "logging": self.host.snapshot().get("logging", {})}
            Path(name).write_text(json.dumps(report, indent=2), encoding="utf-8"); self.set_notice("saved")
        except OSError: self.set_notice(error="LOCAL_STORAGE_UNAVAILABLE")

    def close(self):
        if not self.stop(): return
        self.closed = True; self.status.configure(text=self.t("closing"))
        def finish():
            if self.host.thread is not None and self.host.thread.is_alive(): self.root.after(100, finish)
            else: self.root.destroy()
        finish()


def run(settings, port=8787):
    root = tk.Tk()
    Desktop(root, settings, port)
    root.mainloop()
    return 0
