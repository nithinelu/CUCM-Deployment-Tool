"""Command-line deployer (same engine as the dashboard app).

    py deploy_cli.py template  CUCM_Greenfield.xlsx [--sample]
    py deploy_cli.py validate  CUCM_Greenfield.xlsx [--version 12.5]
    py deploy_cli.py dry-run   CUCM_Greenfield.xlsx [--version 12.5]
    py deploy_cli.py deploy    CUCM_Greenfield.xlsx --host 10.1.1.10 --user axladmin
                               [--version auto] [--sheets "Partitions,Calling Search Spaces"]
                               [--stop-on-error] [--redo] [--in-place]
    py deploy_cli.py inventory --host 10.1.1.10 --user axladmin
    py deploy_cli.py rollback  CUCM_Greenfield_result_xxx.xlsx
"""

import argparse
import getpass
import os
import sys

from cucm_deployer import workbook
from cucm_deployer.axl_client import AXLClient, AXLError
from cucm_deployer.engine import Deployer, results_for_workbook
from cucm_deployer.sample import SAMPLE

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "logs")


def connect(args):
    pwd = os.environ.get("CUCM_AXL_PASSWORD") or getpass.getpass(f"AXL password for {args.user}: ")
    client = AXLClient(args.host, args.user, pwd, verify_tls=args.verify_tls)
    axl, cucm = client.connect(args.version)
    print(f"Connected to {args.host}: CUCM {cucm}, AXL {axl}")
    return client


def main():
    ap = argparse.ArgumentParser(description="Excel-driven CUCM greenfield deployment over AXL")
    ap.add_argument("command", choices=["template", "validate", "dry-run", "deploy", "inventory",
                                        "rollback"])
    ap.add_argument("workbook", nargs="?")
    ap.add_argument("--host")
    ap.add_argument("--user")
    ap.add_argument("--version", default="auto", help="AXL version, e.g. 12.5 (default: auto-detect)")
    ap.add_argument("--sheets", help="comma separated sheet names (default: all)")
    ap.add_argument("--stop-on-error", action="store_true")
    ap.add_argument("--redo", action="store_true", help="also run rows already marked Success")
    ap.add_argument("--in-place", action="store_true", help="write results into the same workbook")
    ap.add_argument("--verify-tls", action="store_true")
    ap.add_argument("--sample", action="store_true", help="template: include the Oman example rows")
    args = ap.parse_args()

    if args.command == "template":
        path = args.workbook or "CUCM_Greenfield.xlsx"
        workbook.build_template(path, SAMPLE if args.sample else None)
        print("Template written:", path)
        return 0

    if args.command == "inventory":
        dep = Deployer(connect(args), log=print)
        for sheet, count in dep.inventory().items():
            print(f"  {sheet:<30} {count}")
        return 0

    if not args.workbook:
        ap.error("workbook path is required")

    if args.command == "rollback":
        base, ext = os.path.splitext(args.workbook)
        out = f"{base}_ROLLBACK{ext}"
        n = workbook.make_rollback(args.workbook, out)
        print(f"{n} row(s) set to Delete -> {out}")
        return 0

    data = workbook.read_workbook(args.workbook)
    client = connect(args) if args.command == "deploy" else None
    version = client.version if client else ("12.5" if args.version == "auto" else args.version)
    dep = Deployer(client, version=version, log=print, log_dir=LOG_DIR)

    issues = dep.validate(data)
    for i in issues:
        print(i)
    errors = [i for i in issues if i.level == "ERROR"]
    print(f"{len(errors)} error(s), {len(issues) - len(errors)} warning/info(s)")
    if args.command == "validate":
        return 1 if errors else 0
    if errors and args.command == "deploy":
        print("Fix the errors first.")
        return 1

    sheets = [s.strip() for s in args.sheets.split(",")] if args.sheets else None
    tasks = dep.plan(data, sheets, skip_done=not args.redo)
    print(f"{len(tasks)} request(s) planned (AXL {version})")
    dep.run(tasks, dry_run=args.command == "dry-run", stop_on_error=args.stop_on_error)
    summary = {}
    for t in tasks:
        summary[t.status] = summary.get(t.status, 0) + 1
    print("Summary:", ", ".join(f"{k} {v}" for k, v in sorted(summary.items())))
    if args.command != "deploy":
        return 0
    out = None if args.in_place else workbook.default_output_path(args.workbook)
    try:
        written = workbook.write_results(args.workbook, results_for_workbook(tasks), out)
        print("Results written to", written)
    except PermissionError:
        print("Could not save results - close the workbook in Excel and run again.")
    return 1 if summary.get("Failed") else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AXLError as e:
        print("AXL error:", e)
        sys.exit(2)
