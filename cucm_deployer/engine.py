"""Turns workbook rows into AXL requests and runs them in dependency order."""

import datetime as dt
import os

from .axl_client import AXLError, build_envelope
from .objects import DEPLOY_PLAN, SHEET_BY_NAME, SHEETS, items, set_path
from .schema import get_schema, vkey
from .workbook import DONE_STATUSES

NONE_TOKEN = "<none>"
TRUE = ("yes", "y", "true", "t", "1", "on", "enabled")
FALSE = ("no", "n", "false", "f", "0", "off", "disabled")

# (sheet, column) -> sheet whose rows define that reference, plus built-in names
REFERENCES = {
    ("Device Pools", "Date Time Group"): "Date Time Groups",
    ("Device Pools", "Region"): "Regions",
    ("Device Pools", "CallManager Group"): "CallManager Groups",
    ("Device Pools", "Media Resource List"): "Media Resource Lists",
    ("Device Pools", "Location"): "Locations",
    ("Device Pools", "SRST Reference"): "SRST References",
    ("Region Relations", "Region"): "Regions",
    ("Media Resource Lists", "Media Resource Groups (in order)"): "Media Resource Groups",
    ("Calling Search Spaces", "Partitions (in order)"): "Partitions",
    ("Route Lists", "Route Groups (in order)"): "Route Groups",
    ("Route Patterns", "Route List"): "Route Lists",
    ("Route Patterns", "Partition"): "Partitions",
    ("Translation Patterns", "Partition"): "Partitions",
    ("Translation Patterns", "CSS"): "Calling Search Spaces",
    ("Directory Numbers", "Partition"): "Partitions",
    ("Directory Numbers", "Line CSS"): "Calling Search Spaces",
    ("Directory Numbers", "Voicemail Profile"): "Voicemail Profiles",
    ("Phones", "Device Pool"): "Device Pools",
    ("Phones", "Device CSS"): "Calling Search Spaces",
    ("Phones", "Owner User ID"): "End Users",
    ("SIP Trunks", "Device Pool"): "Device Pools",
    ("Hunt Lists", "Line Groups (in order)"): "Line Groups",
    ("Hunt Pilots", "Hunt List"): "Hunt Lists",
}
BUILTIN = {"default", "hub_none", "phantom", "shadow", "disable", "use default gateway",
           "standard local route group"}


class Issue:
    def __init__(self, level, sheet, row, message):
        self.level = level      # ERROR | WARN | INFO
        self.sheet = sheet
        self.row = row
        self.message = message

    def __str__(self):
        where = f"{self.sheet} row {self.row}" if self.row else self.sheet
        return f"[{self.level}] {where}: {self.message}"


class Task:
    """One AXL request (relations tasks can cover several Excel rows)."""

    def __init__(self, sheet, stage, action, rows, label):
        self.sheet = sheet
        self.stage = stage          # main | post | delete
        self.action = action
        self.rows = rows
        self.label = label
        self.status = "Pending"
        self.message = ""
        self.request_xml = ""
        self.response_xml = ""


# --------------------------------------------------------------------------
# value conversion
# --------------------------------------------------------------------------
def to_text(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))              # 1001.0 from Excel -> "1001"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return str(v).strip()


def convert(raw, field):
    """Excel cell -> AXL text. Returns None for blank, "" for <none>."""
    if raw is None:
        return None
    text = to_text(raw)
    if text == "":
        return None
    if text.lower() == NONE_TOKEN:
        return ""
    if field.kind == "bool":
        low = text.lower()
        if low in TRUE or raw is True:
            return "true"
        if low in FALSE or raw is False:
            return "false"
        raise ValueError(f"'{field.header}' must be Yes or No (got '{text}')")
    if field.kind == "int":
        try:
            return str(int(float(text)))
        except ValueError:
            raise ValueError(f"'{field.header}' must be a number (got '{text}')")
    return text


# --------------------------------------------------------------------------
# request builders
# --------------------------------------------------------------------------
def build_object(sheet, row, version, with_defaults, warn, action):
    body = {}
    ctx = {"version": version, "row": row.cells, "warn": warn, "action": action}
    for f in sheet.fields:
        val = convert(row.cells.get(f.header), f)
        if val is None and with_defaults and f.default is not None:
            val = convert(f.default, f)
        if val is None:
            continue
        if f.build:
            f.build(body, val, ctx)
        else:
            set_path(body, f.path, val)
    if not with_defaults:
        # a partly filled group (e.g. Location link) still needs its other
        # required members - use the column defaults for those siblings only
        for f in sheet.fields:
            if f.path and "." in f.path and f.default is not None and f.header not in row.cells:
                parent = f.path.rsplit(".", 1)[0]
                if _get_path(body, parent) is not None:
                    set_path(body, f.path, convert(f.default, f))
    for path, raw in row.extra.items():
        text = to_text(raw)
        set_path(body, path, "" if text.lower() == NONE_TOKEN else text)
    if sheet.finish:
        sheet.finish(body, ctx)
    return body


def _get_path(body, path):
    cur = body
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def split_key(sheet, body):
    key = {}
    for k in sheet.key:
        key[k] = body.pop(k, "")
    key.update(sheet.key_extra)
    return key


def add_request(sheet, row, version, warn):
    obj = dict(sheet.const)
    obj.update(build_object(sheet, row, version, True, warn, "add"))
    for k in sheet.deferred:
        obj.pop(k, None)
    return sheet.op("add"), {sheet.tag: obj}


def update_request(sheet, row, version, warn, only=None):
    body = build_object(sheet, row, version, False, warn, "update")
    key = split_key(sheet, body)
    if only is not None:
        body = {k: v for k, v in body.items() if k in only}
    else:
        for k in sheet.deferred:
            body.pop(k, None)
    # a field that is also an alternative key element (Call Pickup Group
    # 'pattern') must be sent as its newXxx element on update
    op = sheet.op("update")
    top = get_schema().top_fields(op, version)
    for k in list(body):
        new = "new" + k[0].upper() + k[1:]
        if k in top and new in top and k not in key:
            body[new] = body.pop(k)
    key.update(body)
    return op, key


def remove_request(sheet, row, version, warn):
    body = build_object(sheet, row, version, False, warn, "delete")
    return sheet.op("remove"), split_key(sheet, body)


def relations_request(sheet, rows, version, warn):
    region = to_text(rows[0].cells.get("Region", ""))
    related = []
    for row in rows:
        item = {}
        for f in sheet.fields:
            if f.path == "name":
                continue
            val = convert(row.cells.get(f.header), f)
            if val is None and f.default is not None:
                val = convert(f.default, f)
            if val is not None:
                set_path(item, f.path, val)
        related.append(item)
    return sheet.op("update"), {"name": region, "relatedRegions": {"relatedRegion": related}}


# --------------------------------------------------------------------------
# Deployer
# --------------------------------------------------------------------------
class Deployer:
    def __init__(self, client=None, version="12.5", log=print, log_dir=None):
        self.client = client
        self.version = client.version if client else version
        self.schema = get_schema()
        self.log = log
        self.log_dir = log_dir
        self._log_file = None

    # -- validation ---------------------------------------------------------
    def validate(self, data):
        issues = []
        defined = {}
        for sh in SHEETS:
            for row in data.get(sh.name, []):
                key = next((f for f in sh.fields if f.key), None)
                if key and row.action != "Delete":
                    defined.setdefault(sh.name, set()).add(to_text(row.cells.get(key.header, "")).lower())
        for sh in SHEETS:
            seen = {}
            for row in data.get(sh.name, []):
                if row.action == "Skip":
                    continue
                if row.action not in ("Add", "Update", "Add/Update", "Delete"):
                    issues.append(Issue("ERROR", sh.name, row.excel_row,
                                        f"unknown Action '{row.action}'"))
                    continue
                if sh.min_version and vkey(self.version) < vkey(sh.min_version):
                    issues.append(Issue("WARN", sh.name, row.excel_row,
                                        f"needs CUCM {sh.min_version}+ - will be skipped"))
                for f in sh.fields:
                    raw = row.cells.get(f.header)
                    if f.req and raw is None and f.default is None and row.action != "Delete" \
                            and not (row.action == "Update" and not f.key):
                        issues.append(Issue("ERROR", sh.name, row.excel_row,
                                            f"'{f.header}' is required"))
                    if raw is None:
                        continue
                    try:
                        val = convert(raw, f)
                    except ValueError as e:
                        issues.append(Issue("ERROR", sh.name, row.excel_row, str(e)))
                        continue
                    if f.choices == "enum" and val and f.path:
                        path = f.path if sh.kind != "relations" else \
                            f"relatedRegions.relatedRegion.{f.path}"
                        allowed = self.schema.enum_for(sh.op("add"), path)
                        if allowed and val not in allowed:
                            issues.append(Issue("WARN", sh.name, row.excel_row,
                                                f"'{f.header}' value '{val}' is not a standard "
                                                f"AXL value"))
                    target = REFERENCES.get((sh.name, f.header))
                    if target and val:
                        for n in items(val):
                            n = n.lower()
                            if n not in BUILTIN and n not in defined.get(target, set()):
                                issues.append(Issue("INFO", sh.name, row.excel_row,
                                                    f"'{f.header}' = '{n}' is not on the "
                                                    f"'{target}' sheet - it must already exist "
                                                    f"on CUCM"))
                if sh.kind != "relations":
                    k = tuple(to_text(row.cells.get(f.header, "")).lower()
                              for f in sh.fields if f.key)
                    if k in seen:
                        issues.append(Issue("WARN", sh.name, row.excel_row,
                                            f"duplicate of row {seen[k]}"))
                    seen[k] = row.excel_row
        return issues

    # -- planning -----------------------------------------------------------
    def plan(self, data, sheets=None, skip_done=True):
        """-> list of Task in execution order (deletes first, reverse order)."""
        wanted = set(sheets) if sheets else {s.name for s in SHEETS}

        def active(row):
            return row.action != "Skip" and not (skip_done and row.status in DONE_STATUSES)

        tasks = []
        main_order = []
        for stage, name in DEPLOY_PLAN:
            if stage == "main" and name not in main_order:
                main_order.append(name)
        for name in reversed(main_order):
            sh = SHEET_BY_NAME[name]
            if name not in wanted or sh.kind == "relations":
                continue
            for row in data.get(name, []):
                if row.action == "Delete" and active(row):
                    tasks.append(Task(name, "delete", "Delete", [row], row.label()))
        for stage, name in DEPLOY_PLAN:
            sh = SHEET_BY_NAME[name]
            if name not in wanted:
                continue
            rows = [r for r in data.get(name, []) if active(r) and r.action != "Delete"]
            if sh.kind == "relations" and stage == "main":
                groups = {}
                for r in rows:
                    groups.setdefault(to_text(r.cells.get("Region", "")), []).append(r)
                for region, grp in groups.items():
                    tasks.append(Task(name, "main", "Update", grp,
                                      f"{region} ({len(grp)} relation(s))"))
            elif stage == "main":
                for r in rows:
                    tasks.append(Task(name, "main", r.action, [r], r.label()))
            elif stage == "post":
                for r in rows:
                    if any(r.cells.get(f.header) is not None for f in sh.fields if f.post):
                        tasks.append(Task(name, "post", "Update", [r],
                                          r.label() + " (devices / primary DN)"))
        return tasks

    # -- execution ----------------------------------------------------------
    def build(self, task):
        """-> (operation, shaped body, warnings)"""
        sh = SHEET_BY_NAME[task.sheet]
        warn = []
        row = task.rows[0]
        if sh.kind == "relations":
            op, body = relations_request(sh, task.rows, self.version, warn)
        elif task.stage == "post":
            op, body = update_request(sh, row, self.version, warn, only=sh.deferred)
        elif task.action == "Delete":
            op, body = remove_request(sh, row, self.version, warn)
        elif task.action == "Update":
            op, body = update_request(sh, row, self.version, warn)
        else:
            op, body = add_request(sh, row, self.version, warn)
        shaped, w2 = self.schema.shape(op, body, self.version)
        return op, shaped, list(dict.fromkeys(warn + w2))

    def run(self, tasks, dry_run=False, stop_on_error=False, cancel=None, progress=None):
        self._open_log()
        total = len(tasks)
        try:
            for i, task in enumerate(tasks, start=1):
                if cancel is not None and cancel.is_set():
                    self.log("Stopped by user.")
                    break
                if progress:
                    progress(i - 1, total, task)
                self._run_one(task, dry_run)
                if progress:
                    progress(i, total, task)
                if task.status == "Failed" and stop_on_error:
                    self.log("Stopping on first error (option).")
                    break
        finally:
            self._close_log()
        return tasks

    def _run_one(self, task, dry_run):
        sh = SHEET_BY_NAME[task.sheet]
        if sh.min_version and vkey(self.version) < vkey(sh.min_version):
            task.status, task.message = "Skipped", f"Needs CUCM {sh.min_version} or later"
            self.log(f"SKIP  {task.sheet}: {task.label} - {task.message}")
            return
        try:
            op, body, warnings = self.build(task)
        except Exception as e:      # bad cell value etc.
            task.status, task.message = "Failed", f"Build error: {e}"
            self.log(f"FAIL  {task.sheet}: {task.label} - {task.message}")
            return
        if not self.schema.op_supported(op, self.version):
            task.status, task.message = "Skipped", f"{op} not available in AXL {self.version}"
            self.log(f"SKIP  {task.sheet}: {task.label} - {task.message}")
            return
        note = ("; ".join(warnings)) if warnings else ""
        if dry_run or self.client is None:
            task.request_xml = build_envelope(self.version, op, body).decode("utf-8")
            task.status = "Validated"
            task.message = f"{op} ready" + (f" | {note}" if note else "")
            self.log(f"DRY   {task.sheet}: {task.label} -> {op}" + (f"  ({note})" if note else ""))
            return
        try:
            ret = self.client.call(op, body, shaped=True)
            task.status = {"add": "Success", "upd": "Updated", "rem": "Deleted"}[op[:3]]
            uuid = ret if isinstance(ret, str) else ""
            task.message = (f"{op} OK {uuid}".strip()) + (f" | {note}" if note else "")
        except AXLError as e:
            if op.startswith("add") and e.is_duplicate:
                if task.action == "Add/Update":
                    self._fallback_update(task, sh, note)
                else:
                    task.status, task.message = "Exists", "Already on CUCM - not changed"
            elif op.startswith("remove") and e.is_not_found:
                task.status, task.message = "Not found", "Not on CUCM - nothing to delete"
            else:
                task.status, task.message = "Failed", str(e)
                self._log_xml(task)
        task.request_xml = self.client.last_request
        task.response_xml = self.client.last_response
        tag = {"Success": "OK  ", "Updated": "UPD ", "Deleted": "DEL ", "Exists": "EXST",
               "Not found": "MISS", "Failed": "FAIL"}.get(task.status, task.status[:4])
        self.log(f"{tag}  {task.sheet}: {task.label} - {task.message}")

    def _fallback_update(self, task, sh, note):
        warn = []
        op, body = update_request(sh, task.rows[0], self.version, warn)
        body, w2 = self.schema.shape(op, body, self.version)
        try:
            self.client.call(op, body, shaped=True)
            task.status, task.message = "Updated", "Existed - updated" + (f" | {note}" if note else "")
        except AXLError as e:
            task.status, task.message = "Failed", f"Existed, update failed: {e}"
            self._log_xml(task)

    # -- logging --------------------------------------------------------------
    def _open_log(self):
        if not self.log_dir:
            return
        os.makedirs(self.log_dir, exist_ok=True)
        name = dt.datetime.now().strftime("deploy_%Y%m%d_%H%M%S.log")
        self._log_file = open(os.path.join(self.log_dir, name), "w", encoding="utf-8")
        self._log_file.write(f"AXL version {self.version}\n")

    def _close_log(self):
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    def _log_xml(self, task):
        if self._log_file and self.client:
            self._log_file.write(f"\n===== FAILED {task.sheet}: {task.label}\n{task.message}\n"
                                 f"--- request\n{self.client.last_request}\n"
                                 f"--- response\n{self.client.last_response}\n")
            self._log_file.flush()

    # -- inventory ------------------------------------------------------------
    def inventory(self, cancel=None):
        """-> {sheet: count or error text} from listXxx on the cluster."""
        out = {}
        for sh in SHEETS:
            if cancel is not None and cancel.is_set():
                break
            if not sh.list_criteria or sh.kind == "relations":
                continue
            if sh.min_version and vkey(self.version) < vkey(sh.min_version):
                out[sh.name] = "n/a"
                continue
            try:
                out[sh.name] = self.client.list_count(sh.op("list"), sh.tag, sh.list_criteria)
            except AXLError as e:
                out[sh.name] = f"error: {e}"[:80]
        return out


def results_for_workbook(tasks):
    """-> [(sheet, excel_row, status, message)] for workbook.write_results.
    A row touched by several tasks (End Users main + post step) keeps the
    first status unless a later step failed."""
    merged = {}
    for t in tasks:
        if t.status == "Pending":
            continue
        for r in t.rows:
            k = (t.sheet, r.excel_row)
            if k not in merged:
                merged[k] = [t.status, t.message]
            else:
                if t.status == "Failed":
                    merged[k][0] = "Failed"
                merged[k][1] += f" | {t.message}"
    return [(s, row, st, msg) for (s, row), (st, msg) in merged.items()]
