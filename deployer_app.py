"""CUCM Greenfield Deployer - dashboard.

Fill the Excel workbook, load it here, Validate -> Dry Run -> Deploy. Works with
CUCM 8.5 to 15 over AXL (version auto-detected). Results are written back into
the workbook (Status / Message / Updated columns).

Run:  pythonw deployer_app.py   (or run_app.bat)
"""

import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from cucm_deployer import __version__, workbook
from cucm_deployer.axl_client import AXL_VERSIONS, AXLClient, AXLError
from cucm_deployer.engine import Deployer, results_for_workbook
from cucm_deployer.objects import DEPLOY_PLAN, SHEET_BY_NAME
from cucm_deployer.sample import SAMPLE
from cucm_deployer.schema import vkey

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
LOG_DIR = os.path.join(HERE, "logs")
TEMPLATES = os.path.join(HERE, "templates")

# palette
BG = "#F3F5F9"
CARD = "#FFFFFF"
NAVY = "#1F3864"
TEAL = "#0E7C86"
MUTED = "#6B7280"
GREEN = "#1E8E3E"
RED = "#C62828"
AMBER = "#B26A00"
BLUE = "#1565C0"

SHEET_ORDER = []
for _stage, _name in DEPLOY_PLAN:
    if _stage == "main" and _name not in SHEET_ORDER:
        SHEET_ORDER.append(_name)

OK_STATUSES = ("Success", "Updated", "Deleted")


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


class KpiCard(tk.Frame):
    def __init__(self, parent, title, color):
        super().__init__(parent, bg=CARD, highlightbackground="#DDE3EC", highlightthickness=1)
        tk.Frame(self, bg=color, height=4).pack(fill="x")
        self.value = tk.Label(self, text="0", font=("Segoe UI", 20, "bold"), fg=color, bg=CARD)
        self.value.pack(anchor="w", padx=12, pady=(6, 0))
        tk.Label(self, text=title, font=("Segoe UI", 9), fg=MUTED, bg=CARD).pack(anchor="w", padx=12,
                                                                                 pady=(0, 8))

    def set(self, v):
        self.value.config(text=str(v))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"CUCM Greenfield Deployer {__version__}")
        self.geometry("1320x860")
        self.minsize(1100, 720)
        self.configure(bg=BG)
        ico = os.path.join(HERE, "app.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except tk.TclError:
                pass
        self.cfg = load_config()
        self.client = None
        self.data = {}
        self.issues = []
        self.tasks = []
        self.inventory = {}
        self.sheet_status = {}       # sheet -> {status: count} from the last run / workbook
        self.ui_queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self._style()
        self._build()
        self.after(100, self._drain)
        wb = self.cfg.get("workbook")
        if wb and os.path.exists(wb):
            self.after(200, lambda: self.load_workbook(wb))

    # ------------------------------------------------------------------ UI
    def _style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", font=("Segoe UI", 10), background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("Card.TLabel", background=CARD)
        st.configure("Card.TCheckbutton", background=CARD)
        st.configure("Head.TLabel", background=CARD, foreground=NAVY, font=("Segoe UI", 11, "bold"))
        st.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Treeview", rowheight=26, font=("Segoe UI", 10), fieldbackground=CARD)
        st.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#E7ECF4",
                     foreground=NAVY)
        st.configure("Accent.TButton", background=TEAL, foreground="white",
                     font=("Segoe UI", 10, "bold"), padding=(14, 6))
        st.map("Accent.TButton", background=[("active", "#0B6B73"), ("disabled", "#9CC9CD")])
        st.configure("Danger.TButton", background=RED, foreground="white",
                     font=("Segoe UI", 10, "bold"), padding=(14, 6))
        st.map("Danger.TButton", background=[("active", "#A31F1F"), ("disabled", "#E3A3A3")])
        st.configure("TButton", padding=(10, 5))
        st.configure("green.Horizontal.TProgressbar", background=TEAL, troughcolor="#E3E8F0")

    def _card(self, parent, title=None, **pack):
        f = ttk.Frame(parent, style="Card.TFrame", padding=12)
        f.pack(**pack)
        if title:
            ttk.Label(f, text=title, style="Head.TLabel").pack(anchor="w", pady=(0, 8))
        return f

    def _build(self):
        # header
        head = tk.Frame(self, bg=NAVY, height=56)
        head.pack(fill="x")
        tk.Label(head, text="CUCM Greenfield Deployer", font=("Segoe UI", 16, "bold"), fg="white",
                 bg=NAVY).pack(side="left", padx=16, pady=10)
        tk.Label(head, text="Excel-driven configuration over AXL  -  CUCM 8.5 to 15",
                 font=("Segoe UI", 10), fg="#C9D3E6", bg=NAVY).pack(side="left", pady=14)
        self.conn_pill = tk.Label(head, text="  Not connected  ", font=("Segoe UI", 10, "bold"),
                                  fg="white", bg="#7A869A")
        self.conn_pill.pack(side="right", padx=16)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        left = tk.Frame(body, bg=BG, width=360)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        self._build_connection(left)
        self._build_workbook(left)
        self._build_options(left)
        self._build_main(right)

    def _build_connection(self, parent):
        c = self._card(parent, "1  Cluster", fill="x")
        self.v_host = tk.StringVar(value=self.cfg.get("host", ""))
        self.v_user = tk.StringVar(value=self.cfg.get("user", ""))
        self.v_pwd = tk.StringVar()
        self.v_ver = tk.StringVar(value=self.cfg.get("version", "Auto"))
        self.v_tls = tk.BooleanVar(value=self.cfg.get("verify_tls", False))
        grid = ttk.Frame(c, style="Card.TFrame")
        grid.pack(fill="x")
        for r, (label, w) in enumerate((
                ("Publisher", ttk.Entry(grid, textvariable=self.v_host)),
                ("AXL user", ttk.Entry(grid, textvariable=self.v_user)),
                ("Password", ttk.Entry(grid, textvariable=self.v_pwd, show="•")),
                ("AXL version", ttk.Combobox(grid, textvariable=self.v_ver, state="readonly",
                                             values=["Auto"] + AXL_VERSIONS, width=10)))):
            ttk.Label(grid, text=label, style="Card.TLabel").grid(row=r, column=0, sticky="w",
                                                                  pady=3, padx=(0, 8))
            w.grid(row=r, column=1, sticky="we", pady=3)
        grid.columnconfigure(1, weight=1)
        ttk.Checkbutton(c, text="Verify TLS certificate", variable=self.v_tls,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(4, 6))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        self.b_connect = ttk.Button(row, text="Connect", style="Accent.TButton", command=self.connect)
        self.b_connect.pack(side="left")
        self.b_inv = ttk.Button(row, text="Cluster inventory", command=self.refresh_inventory,
                                state="disabled")
        self.b_inv.pack(side="left", padx=6)
        self.lbl_cluster = ttk.Label(c, text="Host may be an IP or FQDN. The AXL user needs the "
                                             "'Standard AXL API Access' role.",
                                     style="Muted.TLabel", wraplength=320, justify="left")
        self.lbl_cluster.pack(anchor="w", pady=(8, 0))

    def _build_workbook(self, parent):
        c = self._card(parent, "2  Workbook", fill="x", pady=(12, 0))
        self.v_wb = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.v_wb, style="Muted.TLabel", wraplength=320,
                  justify="left").pack(anchor="w")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Open...", command=self.browse).pack(side="left")
        ttk.Button(row, text="Reload", command=lambda: self.load_workbook(self.v_wb.get())).pack(
            side="left", padx=4)
        ttk.Button(row, text="Open in Excel", command=self.open_excel).pack(side="left")
        row2 = ttk.Frame(c, style="Card.TFrame")
        row2.pack(fill="x", pady=(6, 0))
        ttk.Button(row2, text="New blank template", command=lambda: self.new_template(False)).pack(
            side="left")
        ttk.Button(row2, text="New sample (Oman)", command=lambda: self.new_template(True)).pack(
            side="left", padx=4)

    def _build_options(self, parent):
        c = self._card(parent, "3  Options", fill="x", pady=(12, 0))
        self.v_skip_done = tk.BooleanVar(value=self.cfg.get("skip_done", True))
        self.v_stop = tk.BooleanVar(value=self.cfg.get("stop_on_error", False))
        self.v_inplace = tk.BooleanVar(value=self.cfg.get("in_place", True))
        for text, var in (("Skip rows already deployed (Status = Success)", self.v_skip_done),
                          ("Stop on first error", self.v_stop),
                          ("Write results into the same workbook", self.v_inplace)):
            ttk.Checkbutton(c, text=text, variable=var, style="Card.TCheckbutton").pack(anchor="w",
                                                                                      pady=1)
        ttk.Label(c, text="Unticked: results go to a new *_result_<time>.xlsx copy.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Rollback workbook", command=self.rollback).pack(side="left")
        ttk.Button(row, text="Logs folder", command=lambda: self._open_path(LOG_DIR)).pack(
            side="left", padx=4)

    def _build_main(self, parent):
        kpis = tk.Frame(parent, bg=BG)
        kpis.pack(fill="x")
        self.kpi = {}
        for key, title, color in (("rows", "Rows in workbook", NAVY), ("pending", "Pending", BLUE),
                                  ("ok", "Deployed", GREEN), ("exists", "Already existed", AMBER),
                                  ("failed", "Failed", RED), ("issues", "Validation errors", RED)):
            k = KpiCard(kpis, title, color)
            k.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.kpi[key] = k

        # actions + progress
        act = self._card(parent, fill="x", pady=(12, 0))
        row = ttk.Frame(act, style="Card.TFrame")
        row.pack(fill="x")
        self.b_validate = ttk.Button(row, text="Validate", command=self.validate)
        self.b_validate.pack(side="left")
        self.b_dry = ttk.Button(row, text="Dry run", command=lambda: self.start_run(True))
        self.b_dry.pack(side="left", padx=6)
        self.b_deploy = ttk.Button(row, text="Deploy to CUCM", style="Accent.TButton",
                                   command=lambda: self.start_run(False))
        self.b_deploy.pack(side="left")
        self.b_stop = ttk.Button(row, text="Stop", style="Danger.TButton", command=self.stop,
                                 state="disabled")
        self.b_stop.pack(side="left", padx=6)
        ttk.Button(row, text="Select all", command=lambda: self.tree.selection_set(
            self.tree.get_children())).pack(side="right")
        ttk.Button(row, text="Clear selection", command=lambda: self.tree.selection_remove(
            self.tree.selection())).pack(side="right", padx=6)
        self.progress = ttk.Progressbar(act, style="green.Horizontal.TProgressbar", maximum=1)
        self.progress.pack(fill="x", pady=(10, 2))
        self.v_now = tk.StringVar(value="Load a workbook to begin.")
        ttk.Label(act, textvariable=self.v_now, style="Muted.TLabel").pack(anchor="w")

        # sheet table
        tbl = self._card(parent, "Deployment plan  (select sheets to run only those - none selected "
                                 "= all)", fill="both", expand=True, pady=(12, 0))
        cols = ("order", "sheet", "rows", "add", "update", "delete", "ok", "exists", "failed",
                "cluster", "state")
        heads = ("#", "Sheet", "Rows", "Add", "Update", "Delete", "Deployed", "Existed", "Failed",
                 "On CUCM", "State")
        widths = (36, 230, 60, 55, 65, 60, 75, 70, 60, 75, 160)
        frame = ttk.Frame(tbl, style="Card.TFrame")
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended",
                                 height=12)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("sheet", "state") else "center",
                             stretch=c in ("sheet", "state"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, color in (("failed", "#FDECEC"), ("ok", "#EAF6EC"), ("empty", "#FAFBFC"),
                           ("partial", "#FFF7E6")):
            self.tree.tag_configure(tag, background=color)
        self.tree.tag_configure("empty", foreground="#9AA3AF")

        # bottom tabs
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, pady=(12, 0))
        self.nb = nb
        self.log = ScrolledText(nb, height=10, font=("Consolas", 9), relief="flat")
        self.log.tag_config("ok", foreground=GREEN)
        self.log.tag_config("fail", foreground=RED)
        self.log.tag_config("warn", foreground=AMBER)
        nb.add(self.log, text="  Activity log  ")

        issues_f = ttk.Frame(nb)
        self.issue_tree = ttk.Treeview(issues_f, columns=("level", "sheet", "row", "msg"),
                                       show="headings", height=8)
        for c, h, w in (("level", "Level", 70), ("sheet", "Sheet", 190), ("row", "Row", 50),
                        ("msg", "Message", 700)):
            self.issue_tree.heading(c, text=h)
            self.issue_tree.column(c, width=w, anchor="w", stretch=c == "msg")
        self.issue_tree.tag_configure("ERROR", foreground=RED)
        self.issue_tree.tag_configure("WARN", foreground=AMBER)
        self.issue_tree.tag_configure("INFO", foreground=MUTED)
        self.issue_tree.pack(fill="both", expand=True)
        nb.add(issues_f, text="  Validation  ")

        res_f = ttk.Frame(nb)
        pane = ttk.PanedWindow(res_f, orient="horizontal")
        pane.pack(fill="both", expand=True)
        self.res_tree = ttk.Treeview(pane, columns=("status", "sheet", "item", "msg"),
                                     show="headings", height=8)
        for c, h, w in (("status", "Status", 80), ("sheet", "Sheet", 160), ("item", "Item", 180),
                        ("msg", "Message", 380)):
            self.res_tree.heading(c, text=h)
            self.res_tree.column(c, width=w, anchor="w", stretch=c == "msg")
        for tag, color in (("Failed", RED), ("Success", GREEN), ("Updated", GREEN),
                           ("Deleted", GREEN), ("Exists", AMBER), ("Validated", BLUE)):
            self.res_tree.tag_configure(tag, foreground=color)
        self.res_tree.bind("<<TreeviewSelect>>", self._show_xml)
        pane.add(self.res_tree, weight=3)
        self.xml = ScrolledText(pane, font=("Consolas", 9), relief="flat", width=60)
        pane.add(self.xml, weight=2)
        nb.add(res_f, text="  Results / AXL XML  ")

        self._refresh_table()

    # ----------------------------------------------------------- helpers
    def write_log(self, text):
        tag = None
        if text.startswith(("OK", "UPD", "DEL", "DRY")):
            tag = "ok"
        elif text.startswith(("FAIL", "ERROR", "UI error")):
            tag = "fail"
        elif text.startswith(("EXST", "SKIP", "MISS")):
            tag = "warn"
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")

    def post(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _drain(self):
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:      # never let one UI update stop the queue
                    self.write_log(f"UI error: {e}")
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def set_busy(self, busy, text=None):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.b_validate, self.b_dry, self.b_deploy, self.b_connect):
            b.config(state=state)
        self.b_inv.config(state="disabled" if busy or not self.client else "normal")
        self.b_stop.config(state="normal" if busy else "disabled")
        if text:
            self.v_now.set(text)

    def background(self, work, done=None, text="Working..."):
        if self.busy:
            return
        self.cancel.clear()
        self.set_busy(True, text)

        def runner():
            try:
                result = work()
                err = None
            except Exception as e:      # shown to the user
                result, err = None, e
            self.post(self._finish, done, result, err)
        threading.Thread(target=runner, daemon=True).start()

    def _finish(self, done, result, err):
        self.set_busy(False)
        if err is not None:
            self.write_log(f"ERROR: {err}")
            messagebox.showerror("CUCM Greenfield Deployer", str(err))
            return
        if done:
            done(result)

    def _save_cfg(self):
        self.cfg.update(host=self.v_host.get().strip(), user=self.v_user.get().strip(),
                        version=self.v_ver.get(), verify_tls=self.v_tls.get(),
                        workbook=self.v_wb.get(), skip_done=self.v_skip_done.get(),
                        stop_on_error=self.v_stop.get(), in_place=self.v_inplace.get())
        save_config(self.cfg)

    def _open_path(self, path):
        if not os.path.splitext(path)[1]:
            os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except (AttributeError, OSError):
            subprocess.Popen(["xdg-open", path])

    @property
    def axl_version(self):
        if self.client:
            return self.client.version
        v = self.v_ver.get()
        return "12.5" if v == "Auto" else v

    # ----------------------------------------------------------- cluster
    def connect(self):
        host, user, pwd = self.v_host.get().strip(), self.v_user.get().strip(), self.v_pwd.get()
        if not host or not user or not pwd:
            messagebox.showwarning("Connect", "Enter publisher, AXL user and password.")
            return
        self._save_cfg()
        client = AXLClient(host, user, pwd, verify_tls=self.v_tls.get())

        def work():
            return client.connect(self.v_ver.get())

        def done(res):
            axl, cucm = res
            self.client = client
            self.conn_pill.config(text=f"  {host}  |  CUCM {cucm}  |  AXL {axl}  ", bg=GREEN)
            self.lbl_cluster.config(text=f"Connected. CUCM {cucm}, using AXL schema {axl}.")
            self.write_log(f"Connected to {host}: CUCM {cucm}, AXL {axl}")
            self.b_inv.config(state="normal")
            self.refresh_inventory()
        self.background(work, done, f"Connecting to {host}...")

    def refresh_inventory(self):
        if not self.client:
            return
        dep = Deployer(self.client, log=lambda t: self.post(self.write_log, t))

        def done(inv):
            self.inventory = inv
            self._refresh_table()
            self.v_now.set("Cluster inventory refreshed.")
        self.background(lambda: dep.inventory(self.cancel), done, "Reading cluster inventory...")

    # ----------------------------------------------------------- workbook
    def browse(self):
        path = filedialog.askopenfilename(title="Open deployment workbook",
                                          filetypes=[("Excel workbook", "*.xlsx")],
                                          initialdir=os.path.dirname(self.v_wb.get()) or TEMPLATES)
        if path:
            self.load_workbook(path)

    def new_template(self, sample):
        name = "CUCM_Greenfield_Sample_Oman.xlsx" if sample else "CUCM_Greenfield.xlsx"
        path = filedialog.asksaveasfilename(title="Create workbook", defaultextension=".xlsx",
                                            initialfile=name, initialdir=TEMPLATES,
                                            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            workbook.build_template(path, SAMPLE if sample else None)
        except PermissionError:
            messagebox.showerror("Template", "That file is open in Excel - close it first.")
            return
        self.write_log(f"Created {'sample' if sample else 'blank'} workbook {path}")
        self.load_workbook(path)

    def open_excel(self):
        if self.v_wb.get() and os.path.exists(self.v_wb.get()):
            self._open_path(self.v_wb.get())

    def load_workbook(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            self.data = workbook.read_workbook(path)
        except PermissionError:
            messagebox.showerror("Workbook", "Cannot read the workbook - is it locked?")
            return
        except Exception as e:
            messagebox.showerror("Workbook", f"Cannot read {path}:\n{e}")
            return
        self.v_wb.set(path)
        self.tasks = []
        self._apply_statuses([])
        self._save_cfg()
        total = sum(len(v) for v in self.data.values())
        self.write_log(f"Loaded {os.path.basename(path)}: {total} row(s) in "
                       f"{sum(1 for v in self.data.values() if v)} sheet(s)")
        self.v_now.set(f"Workbook loaded - {total} row(s). Validate, then Dry run or Deploy.")
        self._refresh_table()
        self.validate(quiet=True)

    # ----------------------------------------------------------- table / KPIs
    def _refresh_table(self):
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        tot = {"rows": 0, "ok": 0, "exists": 0, "failed": 0, "pending": 0}
        for i, name in enumerate(SHEET_ORDER, start=1):
            rows = self.data.get(name, [])
            acts = {"Add": 0, "Update": 0, "Delete": 0}
            for r in rows:
                if r.action in ("Add", "Add/Update"):
                    acts["Add"] += 1
                elif r.action in acts:
                    acts[r.action] += 1
            st = self.sheet_status.get(name, {})
            ok = sum(st.get(s, 0) for s in OK_STATUSES)
            ex, fl = st.get("Exists", 0), st.get("Failed", 0)
            n = len([r for r in rows if r.action != "Skip"])
            inv = self.inventory.get(name, "")
            state = ""
            tag = "empty" if not rows else ""
            if fl:
                state, tag = f"{fl} failed", "failed"
            elif rows and ok + ex >= n and n:
                state, tag = "Done", "ok"
            elif ok or ex:
                state, tag = "Partly deployed", "partial"
            elif st.get("Validated"):
                state = "Dry run OK"
            elif rows:
                state = "Ready"
            sh = SHEET_BY_NAME[name]
            if sh.min_version and self.client and \
                    tuple(map(int, self.axl_version.split("."))) < tuple(map(int, sh.min_version.split("."))):
                state = f"Needs CUCM {sh.min_version}+"
            self.tree.insert("", "end", iid=name, values=(
                i, name, len(rows) or "", acts["Add"] or "", acts["Update"] or "",
                acts["Delete"] or "", ok or "", ex or "", fl or "",
                inv if isinstance(inv, int) else ("!" if str(inv).startswith("error") else inv),
                state), tags=(tag,))
            tot["rows"] += len(rows)
            tot["ok"] += ok
            tot["exists"] += ex
            tot["failed"] += fl
            tot["pending"] += max(0, n - ok - ex - fl)
        for s in sel:
            if self.tree.exists(s):
                self.tree.selection_add(s)
        for k, v in tot.items():
            self.kpi[k].set(v)
        self.kpi["issues"].set(sum(1 for i in self.issues if i.level == "ERROR"))

    # ----------------------------------------------------------- actions
    def _need_workbook(self):
        if not self.data:
            messagebox.showinfo("Workbook", "Open or create a workbook first.")
            return False
        return True

    def validate(self, quiet=False):
        if not self.data:
            if not quiet:
                self._need_workbook()
            return []
        dep = Deployer(self.client, version=self.axl_version, log=lambda *_: None)
        self.issues = dep.validate(self.data)
        self.issue_tree.delete(*self.issue_tree.get_children())
        for i in self.issues:
            self.issue_tree.insert("", "end", values=(i.level, i.sheet, i.row or "", i.message),
                                   tags=(i.level,))
        errors = sum(1 for i in self.issues if i.level == "ERROR")
        warns = len(self.issues) - errors
        self.kpi["issues"].set(errors)
        msg = f"Validation (AXL {self.axl_version}): {errors} error(s), {warns} warning/info."
        self.write_log(msg)
        self.v_now.set(msg)
        if not quiet:
            self.nb.select(1)
        return self.issues

    def start_run(self, dry_run):
        if not self._need_workbook():
            return
        self.load_workbook(self.v_wb.get())          # pick up edits made in Excel
        if not dry_run and not self.client:
            messagebox.showinfo("Deploy", "Connect to the CUCM publisher first.")
            return
        issues = self.validate(quiet=True)
        if any(i.level == "ERROR" for i in issues):
            self.nb.select(1)
            messagebox.showerror("Validation", "Fix the validation errors first (Validation tab).")
            return
        sheets = list(self.tree.selection()) or None
        dep = Deployer(None if dry_run else self.client, version=self.axl_version,
                       log=lambda t: self.post(self.write_log, t), log_dir=LOG_DIR)
        tasks = dep.plan(self.data, sheets, skip_done=self.v_skip_done.get())
        if not tasks:
            messagebox.showinfo("Nothing to do", "No rows to run (all Skip, or already deployed).")
            return
        n_del = sum(1 for t in tasks if t.stage == "delete")
        if not dry_run:
            host = self.v_host.get()
            text = (f"Send {len(tasks)} AXL request(s) to {host} (AXL {self.axl_version})?"
                    + (f"\n\n{n_del} of them DELETE objects." if n_del else ""))
            if not messagebox.askyesno("Deploy to CUCM", text, icon="warning"):
                return
        self.tasks = tasks
        self.res_tree.delete(*self.res_tree.get_children())
        self.progress.config(maximum=len(tasks), value=0)
        self.nb.select(0)
        label = "Dry run" if dry_run else "Deploying"
        self.write_log(f"--- {label}: {len(tasks)} request(s) ---")

        def progress(i, total, task):
            # snapshot now - the worker thread moves on before the UI catches up
            self.post(self._progress, i, total, task, label, task.status, task.message)

        def work():
            return dep.run(tasks, dry_run=dry_run, stop_on_error=self.v_stop.get(),
                           cancel=self.cancel, progress=progress)
        self.background(work, lambda res: self._run_done(res, dry_run), f"{label}...")

    def _progress(self, i, total, task, label, status, message):
        self.progress.config(value=i)
        self.v_now.set(f"{label} {i}/{total}  -  {task.sheet}: {task.label}")
        iid = str(id(task))
        if status != "Pending" and not self.res_tree.exists(iid):
            self.res_tree.insert("", "end", iid=iid,
                                 values=(status, task.sheet, task.label, message), tags=(status,))
            self.res_tree.see(iid)

    def _run_done(self, tasks, dry_run):
        summary = {}
        for t in tasks:
            summary[t.status] = summary.get(t.status, 0) + 1
        text = ", ".join(f"{k} {v}" for k, v in sorted(summary.items()))
        self.write_log(f"--- Finished: {text}")
        self._apply_statuses(results_for_workbook(tasks))
        if not dry_run:
            path = self.v_wb.get()
            out = None if self.v_inplace.get() else workbook.default_output_path(path)
            while True:
                try:
                    written = workbook.write_results(path, results_for_workbook(tasks), out)
                    self.write_log(f"Results written to {written}")
                    break
                except PermissionError:
                    if not messagebox.askretrycancel(
                            "Save results", f"{os.path.basename(out or path)} is open in Excel.\n"
                                            "Close it and press Retry."):
                        self.write_log("Results NOT saved to the workbook.")
                        break
            if self.v_inplace.get():
                self.load_workbook(path)
            if self.client:
                self.after(300, self.refresh_inventory)
        self._refresh_table()
        self.v_now.set(f"{'Dry run' if dry_run else 'Deployment'} finished: {text}")
        self.nb.select(2)
        if summary.get("Failed"):
            messagebox.showwarning("Finished", f"Finished with failures:\n{text}\n\n"
                                               "See the Results tab (select a row for the XML).")

    def _apply_statuses(self, results):
        """Put run results on the in-memory rows and recount per sheet."""
        by_row = {(sheet, row): status for sheet, row, status, _ in results}
        self.sheet_status = {}
        for sheet, rows in self.data.items():
            counts = {}
            for r in rows:
                r.status = by_row.get((sheet, r.excel_row), r.status)
                if r.status:
                    counts[r.status] = counts.get(r.status, 0) + 1
            self.sheet_status[sheet] = counts

    def _show_xml(self, _event=None):
        sel = self.res_tree.selection()
        if not sel:
            return
        task = next((t for t in self.tasks if str(id(t)) == sel[0]), None)
        self.xml.delete("1.0", "end")
        if task:
            self.xml.insert("end", f"{task.status}: {task.message}\n\n--- request ---\n"
                                   f"{task.request_xml}\n")
            if task.response_xml:
                self.xml.insert("end", f"--- response ---\n{task.response_xml}\n")

    def stop(self):
        self.cancel.set()
        self.v_now.set("Stopping after the current request...")

    def rollback(self):
        path = filedialog.askopenfilename(title="Workbook with deployment results",
                                          filetypes=[("Excel workbook", "*.xlsx")],
                                          initialdir=os.path.dirname(self.v_wb.get()) or TEMPLATES)
        if not path:
            return
        base, ext = os.path.splitext(path)
        out = f"{base}_ROLLBACK{ext}"
        try:
            n = workbook.make_rollback(path, out)
        except PermissionError:
            messagebox.showerror("Rollback", "Close the workbook in Excel first.")
            return
        self.write_log(f"Rollback workbook: {n} row(s) set to Delete -> {out}")
        if messagebox.askyesno("Rollback", f"{n} object(s) that were added are now Delete rows in\n"
                                           f"{out}\n\nLoad it now? (Review, then Deploy to remove "
                                           f"them.)"):
            self.load_workbook(out)


if __name__ == "__main__":
    App().mainloop()
