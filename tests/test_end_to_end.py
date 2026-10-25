"""End-to-end: sample workbook -> fake AXL server -> results -> rerun -> rollback.

    py tests/test_end_to_end.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cucm_deployer import workbook                        # noqa: E402
from cucm_deployer.axl_client import AXLClient             # noqa: E402
from cucm_deployer.engine import Deployer, results_for_workbook  # noqa: E402
from cucm_deployer.sample import SAMPLE                    # noqa: E402
import fake_axl                                            # noqa: E402


def run(path, client, **kw):
    data = workbook.read_workbook(path)
    dep = Deployer(client, log=lambda *_: None)
    tasks = dep.run(dep.plan(data, **kw))
    out = workbook.write_results(path, results_for_workbook(tasks))
    stats = {}
    for t in tasks:
        stats[t.status] = stats.get(t.status, 0) + 1
    return tasks, stats, out


def main():
    srv, store = fake_axl.start(8098, "14.0.1.13900-155")
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "sample.xlsx")
    workbook.build_template(path, SAMPLE)

    client = AXLClient("http://127.0.0.1:8098", "u", "p")
    axl, cucm = client.connect("auto")
    assert (axl, cucm) == ("14.0", "14.0.1.13900-155"), (axl, cucm)

    tasks, stats, _ = run(path, client)
    print("first run :", stats)
    assert stats.get("Failed", 0) == 0, [t.message for t in tasks if t.status == "Failed"]

    tasks, stats, _ = run(path, client)
    print("second run:", stats, "(done rows skipped)")
    assert not tasks, "rows marked Success must be skipped"

    tasks, stats, _ = run(path, client, skip_done=False)
    print("redo run  :", stats)
    assert stats.get("Exists", 0) > 0

    inv = Deployer(client, log=lambda *_: None).inventory()
    print("inventory :", {k: v for k, v in inv.items() if v})
    assert inv["Partitions"] == 5

    rb = os.path.join(tmp, "rollback.xlsx")
    n = workbook.make_rollback(path, rb)
    tasks, stats, _ = run(rb, client)
    print(f"rollback  : {n} rows ->", stats)
    missing = [t.label for t in tasks if t.status != "Deleted"]
    print("not deleted:", missing)
    assert stats.get("Deleted") == n, stats
    left = {k for k in store.objects}
    print("left on fake CUCM:", left)
    assert not left, left
    srv.shutdown()
    print("OK")


if __name__ == "__main__":
    main()
