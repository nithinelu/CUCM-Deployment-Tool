"""CUCM AXL (SOAP) client that works with every CUCM release from 8.5 to 15.

No WSDL download is needed (the old script needed schema/<version>/AXLAPI.wsdl,
which was never in the repository). Requests are plain dicts:

    {"css": {"name": "CSS_Internal", "members": {"member": [{...}, {...}]}}}

  * dict   -> child elements (re-ordered to the XSD sequence by schema.py)
  * list   -> the same tag repeated
  * ""     -> empty element (clears a value / nil reference)
  * None   -> element omitted

Responses are converted back to dicts the same way (repeated tags -> list).
"""

import requests
import urllib3
from lxml import etree

from .schema import get_schema, vkey

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
AXL_VERSIONS = ["15.0", "14.0", "12.5", "12.0", "11.5", "11.0", "10.5", "10.0", "9.1", "9.0", "8.5"]


class AXLError(Exception):
    """AXL SOAP fault or transport problem, with a readable message."""

    def __init__(self, message, code=None, operation=None):
        super().__init__(message)
        self.code = code
        self.operation = operation

    @property
    def is_duplicate(self):
        text = str(self).lower()
        return "duplicate" in text or "already exists" in text or str(self.code) == "-239"

    @property
    def is_not_found(self):
        text = str(self).lower()
        return "not found" in text or "was not found" in text or str(self.code) == "5007"


# --------------------------------------------------------------------------
# dict <-> XML
# --------------------------------------------------------------------------
def _append(parent, tag, value):
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            _append(parent, tag, item)
        return
    el = etree.SubElement(parent, tag)
    if isinstance(value, dict):
        for k, v in value.items():
            if k.startswith("@"):            # "@uuid": "..." -> attribute
                if v is not None:
                    el.set(k[1:], str(v))
            elif k == "_text":               # text next to attributes
                el.text = str(v)
            else:
                _append(el, k, v)
    elif isinstance(value, bool):
        el.text = "true" if value else "false"
    else:
        el.text = str(value)


def _local(tag):
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def element_to_value(el):
    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        text = (el.text or "").strip()
        if el.attrib and not text:
            return {f"@{k}": v for k, v in el.attrib.items()}
        return text
    out = {f"@{k}": v for k, v in el.attrib.items()}
    for c in children:
        key = _local(c.tag)
        val = element_to_value(c)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(val)
        else:
            out[key] = val
    return out


def as_list(value):
    """AXL returns one item as a dict and several as a list - normalise."""
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


def text_of(value):
    if isinstance(value, dict):
        return value.get("_value_1", "") or ""
    return value or ""


def build_envelope(version, operation, body):
    ns = f"http://www.cisco.com/AXL/API/{version}"
    env = etree.Element(f"{{{SOAP_NS}}}Envelope", nsmap={"soapenv": SOAP_NS, "ns": ns})
    etree.SubElement(env, f"{{{SOAP_NS}}}Header")
    b = etree.SubElement(env, f"{{{SOAP_NS}}}Body")
    op = etree.SubElement(b, f"{{{ns}}}{operation}")
    for k, v in (body or {}).items():
        if k.startswith("@"):
            op.set(k[1:], str(v))
        else:
            _append(op, k, v)
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class AXLClient:
    def __init__(self, host, username, password, version="auto", port=8443,
                 verify_tls=False, timeout=60):
        self.host = host.strip()
        self.version = "12.5" if version in (None, "", "auto", "Auto") else version
        self.timeout = timeout
        # "http://127.0.0.1:8080" style hosts are used by the test server
        if self.host.startswith(("http://", "https://")):
            self.url = self.host.rstrip("/") + "/axl/"
        else:
            self.url = f"https://{self.host}:{int(port)}/axl/"
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_tls
        if not verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.cucm_version = ""
        self.last_request = ""
        self.last_response = ""
        self.schema = get_schema()

    # -- low level --------------------------------------------------------
    def build_envelope(self, operation, body):
        return build_envelope(self.version, operation, body)

    def prepare(self, operation, body):
        """Order/filter the body for this cluster's AXL version -> (body, warnings)."""
        return self.schema.shape(operation, body or {}, self.version)

    def call(self, operation, body=None, shaped=False):
        if not shaped:
            body, _ = self.prepare(operation, body)
        payload = self.build_envelope(operation, body)
        self.last_request = payload.decode("utf-8")
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"CUCM:DB ver={self.version} {operation}"',
        }
        try:
            r = self.session.post(self.url, data=payload, headers=headers, timeout=self.timeout)
        except requests.exceptions.SSLError as e:
            raise AXLError(f"TLS error talking to {self.host}: {e}. "
                           "Untick 'Verify certificate' or install the CUCM CA.", operation=operation)
        except requests.exceptions.RequestException as e:
            raise AXLError(f"Cannot reach {self.url}: {e}", operation=operation)
        self.last_response = r.text
        if r.status_code == 401:
            raise AXLError("Authentication failed (HTTP 401). Check the AXL user/password and "
                           "that the user has the 'Standard AXL API Access' role.", 401, operation)
        if r.status_code == 599:
            raise AXLError(f"AXL version {self.version} is not supported by this CUCM (HTTP 599).",
                           599, operation)
        try:
            root = etree.fromstring(r.content)
        except etree.XMLSyntaxError:
            raise AXLError(f"HTTP {r.status_code}: non-XML reply from {self.url}: {r.text[:300]}",
                           r.status_code, operation)
        fault = root.find(f".//{{{SOAP_NS}}}Fault")
        if fault is not None:
            msg = fault.findtext("faultstring") or "SOAP fault"
            code = None
            for el in fault.iter():
                name = _local(el.tag)
                if name == "axlmessage" and el.text:
                    msg = el.text
                elif name == "axlcode" and el.text:
                    code = el.text
            raise AXLError(f"{operation}: {msg}", code, operation)
        if r.status_code >= 400:
            raise AXLError(f"{operation}: HTTP {r.status_code}", r.status_code, operation)
        body_el = root.find(f"{{{SOAP_NS}}}Body")
        resp = next((c for c in body_el if isinstance(c.tag, str)), None) if body_el is not None else None
        if resp is None:
            return {}
        value = element_to_value(resp)
        return value.get("return", value) if isinstance(value, dict) else value

    # -- helpers ----------------------------------------------------------
    def get_version(self):
        ret = self.call("getCCMVersion", {"processNodeName": None})
        return ret.get("componentVersion", {}).get("version", "") if isinstance(ret, dict) else ""

    def detect_version(self):
        """Find an AXL version the cluster accepts, then switch to the one that
        matches the CUCM release (e.g. CUCM 14.0.1.13900-155 -> AXL 14.0)."""
        errors = []
        for v in AXL_VERSIONS:
            self.version = v
            try:
                cucm = self.get_version()
            except AXLError as e:
                if e.code == 401:
                    raise
                errors.append(f"{v}: {e}")
                continue
            self.cucm_version = cucm
            major = cucm.split(".")
            if len(major) >= 2:
                exact = f"{major[0]}.{major[1]}"
                if exact in AXL_VERSIONS and vkey(exact) <= vkey(v):
                    self.version = exact
                elif f"{major[0]}.0" in AXL_VERSIONS and vkey(f"{major[0]}.0") <= vkey(v):
                    self.version = f"{major[0]}.0"
            return self.version, cucm
        raise AXLError("No supported AXL version found:\n" + "\n".join(errors))

    def connect(self, version="auto"):
        """Detect (or verify) the AXL version. Returns (axl_version, cucm_version)."""
        if version in (None, "", "auto", "Auto"):
            return self.detect_version()
        self.version = version
        self.cucm_version = self.get_version()
        return self.version, self.cucm_version

    def list_count(self, operation, item_tag, criteria_field):
        """Number of objects on the cluster for a listXxx operation."""
        ret = self.call(operation, {"searchCriteria": {criteria_field: "%"},
                                    "returnedTags": {criteria_field: ""}}, shaped=True)
        return len(as_list(ret.get(item_tag))) if isinstance(ret, dict) else 0
