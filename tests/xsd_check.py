"""Developer check: every request built from the sample workbook must validate
against Cisco's real AXL XSD, for every bundled AXL version.

    py tests/xsd_check.py <schema_root>   (folders 8.5 ... 12.5 with AXLSoap.xsd)
"""

import os
import sys
import tempfile

from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cucm_deployer import workbook                       # noqa: E402
from cucm_deployer.engine import Deployer                # noqa: E402
from cucm_deployer.sample import SAMPLE                   # noqa: E402


# The XSD makes <dirn> mandatory on Universal Device Template lines, but a UDT
# has no DN of its own - CUCM accepts the line without it (as the original
# zeep script sent it, with xsd.SkipValue).
KNOWN = ("Element 'line': Missing child element(s). Expected is ( dirn ).",)


def main(root, versions=None):
    tmp = os.path.join(tempfile.mkdtemp(), "sample.xlsx")
    workbook.build_template(tmp, SAMPLE)
    data = workbook.read_workbook(tmp)
    # exercise Update / Delete / Add/Update builders too
    variants = {"Add": data}
    failures = 0
    for v in versions or ["8.5", "9.1", "10.0", "10.5", "11.0", "11.5", "12.0", "12.5"]:
        xsd = etree.XMLSchema(etree.parse(os.path.join(root, v, "AXLSoap.xsd")))
        dep = Deployer(version=v, log=lambda *_: None)
        checked = 0
        for action in ("Add", "Update", "Delete"):
            for rows in data.values():
                for r in rows:
                    r.action = action
            for task in dep.plan(data):
                if task.status != "Pending":
                    continue
                dep._run_one(task, dry_run=True)
                if task.status == "Skipped":
                    continue
                if task.status != "Validated":
                    print(f"  {v} BUILD FAIL {task.sheet} {task.label}: {task.message}")
                    failures += 1
                    continue
                env = etree.fromstring(task.request_xml.encode())
                body = env[1]
                op = body[0]
                # real XSD uses the targetNamespace of that schema version
                ns = xsd_ns = f"http://www.cisco.com/AXL/API/{v}"
                op.tag = f"{{{xsd_ns}}}{etree.QName(op).localname}"
                doc = etree.ElementTree(op)
                checked += 1
                if not xsd.validate(doc):
                    errors = [e.message for e in xsd.error_log if e.message not in KNOWN]
                    if not errors:
                        continue
                    failures += 1
                    errs = "; ".join(errors[:3])
                    print(f"  {v} XSD FAIL {action} {task.sheet} {task.label}: {errs}")
        print(f"AXL {v}: {checked} requests checked")
    print("FAILURES:", failures)
    return failures


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1], sys.argv[2:] or None) else 0)
