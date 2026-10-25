"""Tiny fake CUCM AXL server for testing the deployer without a cluster.

    py tests/fake_axl.py [port] [cucm_version]      (default 8099, 14.0.1.13900-155)

Then connect the app to host  http://127.0.0.1:8099  (any user/password).
Keeps objects in memory: add -> duplicate fault if it exists, update/remove ->
not-found fault if missing, listXxx returns what was added.
"""

import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lxml import etree

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
KEYS = ("name", "pattern", "userid", "domainName", "dirn", "conferenceNowNumber")


def local(tag):
    return tag.split("}", 1)[-1]


class Store:
    def __init__(self, version):
        self.version = version
        self.objects = {}          # (obj, key) -> element
        self.calls = []
        self.lock = threading.Lock()

    @staticmethod
    def key_of(el):
        for k in KEYS:
            child = el.find(k)
            if child is not None and (child.text or "").strip():
                part = el.find("routePartitionName") if k != "name" else None
                pt = (part.text or "").strip() if part is not None else ""
                return f"{(child.text or '').strip()}|{pt}"
        return None

    def handle(self, op_el):
        op = local(op_el.tag)
        self.calls.append(op)
        with self.lock:
            if op == "getCCMVersion":
                return f"<componentVersion><version>{self.version}</version></componentVersion>"
            for verb in ("add", "update", "remove", "list", "get"):
                if op.startswith(verb):
                    obj = op[len(verb):]
                    break
            else:
                raise Fault(f"Unknown operation {op}", 5000)
            if verb == "add":
                el = op_el[0]
                key = self.key_of(el)
                if (obj, key) in self.objects:
                    raise Fault("Could not insert new row - duplicate value in a UNIQUE INDEX "
                                "column (Unique Index:).", -239)
                self.objects[(obj, key)] = el
                return "{" + str(uuid.uuid4()).upper() + "}"
            if verb in ("update", "remove", "get"):
                key = self.key_of(op_el)
                if (obj, key) not in self.objects:
                    raise Fault(f"Item not valid: The specified {obj} was not found", 5007)
                if verb == "remove":
                    del self.objects[(obj, key)]
                return "{" + str(uuid.uuid4()).upper() + "}"
            if verb == "list":
                tag = obj[0].lower() + obj[1:]
                n = sum(1 for (o, _) in self.objects if o == obj)
                return "".join(f"<{tag}><name>x{i}</name></{tag}>" for i in range(n))
        return ""


class Fault(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            root = etree.fromstring(data)
            body = root.find(f"{{{SOAP}}}Body")
            op_el = body[0]
            op = local(op_el.tag)
            try:
                ret = store.handle(op_el)
                xml = (f'<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="{SOAP}"><soapenv:Body>'
                       f'<ns:{op}Response xmlns:ns="http://www.cisco.com/AXL/API/{store.version[:4]}">'
                       f"<return>{ret}</return></ns:{op}Response></soapenv:Body></soapenv:Envelope>")
                status = 200
            except Fault as f:
                xml = (f'<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="{SOAP}"><soapenv:Body>'
                       f"<soapenv:Fault><faultcode>soapenv:Server</faultcode><faultstring>{f}"
                       f"</faultstring><detail><axlError><axlcode>{f.code}</axlcode><axlmessage>{f}"
                       f"</axlmessage><request>{op}</request></axlError></detail></soapenv:Fault>"
                       f"</soapenv:Body></soapenv:Envelope>")
                status = 500
            out = xml.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
    return Handler


def start(port=8099, version="14.0.1.13900-155"):
    store = Store(version)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, store


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    ver = sys.argv[2] if len(sys.argv) > 2 else "14.0.1.13900-155"
    srv, _ = start(port, ver)
    print(f"Fake AXL {ver} on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
