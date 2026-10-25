"""Developer tool: build cucm_deployer/axl_schema.json from Cisco AXL XSD files.

AXL validates the ORDER of child elements (xsd:sequence), and each CUCM release
adds fields. This script walks the request types of the operations the deployer
uses, for every AXL schema version given, and writes one compact JSON:

    {"versions": ["8.5", ...],
     "trees":  {"12.5": {"addCss": {"c": [{"n": "css", "k": {"c": [...]}}]}}},
     "enums":  {"XPartitionUsage": ["General", ...]}}

  One tree per AXL version, because element order differs between releases
  (e.g. css/name is first in 8.5/9.1 and last from 10.0).
  n = element name, k = child node (complex element), t = XSD type name, x = 1 when repeatable,
  r = 1 when required (minOccurs >= 1, outside a choice),
  d = XSD default value, z = 1 when nillable (may be sent empty).

Usage:
    py tools/build_schema_map.py <schema_root>   (folders 10.0, 10.5, ... each with AXLSoap.xsd)
"""

import json
import os
import sys

from lxml import etree

XS = "{http://www.w3.org/2001/XMLSchema}"
MAX_DEPTH = 7

# Operations used by cucm_deployer/objects.py (add + update for each object).
OBJECTS = [
    "DateTimeGroup", "Region", "Location", "CallManagerGroup", "RoutePartition", "Css",
    "MediaResourceGroup", "MediaResourceList", "Srst", "DevicePool", "SipTrunk", "Gateway",
    "RouteGroup", "RouteList", "RoutePattern", "TransPattern",
    "CallingPartyTransformationPattern", "CalledPartyTransformationPattern",
    "VoiceMailPilot", "VoiceMailProfile", "ConferenceNow", "UniversalLineTemplate",
    "UniversalDeviceTemplate", "Line", "Phone", "User", "LineGroup", "HuntList", "HuntPilot",
    "CallPickupGroup",
]
EXTRA_OPS = ["getCCMVersion"]


def local(tag):
    return tag.split(":", 1)[-1] if tag else tag


class Schema:
    def __init__(self, folder):
        self.types = {}
        self.elements = {}
        self.simple = {}
        for fn in ("AXLSoap.xsd", "AXLEnums.xsd"):
            path = os.path.join(folder, fn)
            if not os.path.exists(path):
                continue
            root = etree.parse(path).getroot()
            for el in root:
                if el.tag == XS + "complexType":
                    self.types[el.get("name")] = el
                elif el.tag == XS + "simpleType":
                    self.simple[el.get("name")] = el
                elif el.tag == XS + "element":
                    self.elements[el.get("name")] = el

    def enum_values(self, type_name):
        st = self.simple.get(type_name)
        if st is None:
            return None
        r = st.find(XS + "restriction")
        if r is None:
            return None
        vals = [e.get("value") for e in r.findall(XS + "enumeration")]
        if vals:
            return vals
        base = local(r.get("base") or "")
        return self.enum_values(base) if base in self.simple else None

    # -- content walking -------------------------------------------------
    def type_children(self, type_name, depth, seen):
        ct = self.types.get(type_name)
        if ct is None:
            return None
        return self.complex_children(ct, depth, seen | {type_name})

    def complex_children(self, ct, depth, seen):
        out = []
        for child in ct:
            if child.tag == XS + "complexContent":
                for d in child:
                    if d.tag in (XS + "extension", XS + "restriction"):
                        base = local(d.get("base"))
                        if d.tag == XS + "extension" and base in self.types:
                            out += self.type_children(base, depth, seen) or []
                        out += self.particles(d, depth, seen, in_choice=False, top=True)
            elif child.tag in (XS + "sequence", XS + "choice", XS + "all"):
                out += self.particles(ct, depth, seen, in_choice=False, top=True)
                break
        return out

    def particles(self, parent, depth, seen, in_choice, top=False):
        """top: parent is the complexType/extension itself - Cisco marks most
        type-level sequences minOccurs=0, which does not make the fields optional."""
        out = []
        for p in parent:
            if p.tag == XS + "element":
                out.append(self.element(p, depth, seen, in_choice))
            elif p.tag == XS + "sequence":
                optional = in_choice or (p.get("minOccurs") == "0" and not top)
                out += self.particles(p, depth, seen, optional)
            elif p.tag == XS + "choice":
                out += self.particles(p, depth, seen, True)
            elif p.tag == XS + "all":
                out += self.particles(p, depth, seen, in_choice)
        return out

    def element(self, el, depth, seen, in_choice):
        name = el.get("name") or local(el.get("ref"))
        node = {"n": name}
        if el.get("maxOccurs") not in (None, "1"):
            node["x"] = 1
        if not in_choice and el.get("minOccurs", "1") != "0":
            node["r"] = 1
        t = local(el.get("type") or "")
        if t:
            node["t"] = t
        if el.get("default") is not None:
            node["d"] = el.get("default")
        if el.get("nillable") == "true":
            node["z"] = 1
        if depth >= MAX_DEPTH:
            return node
        anon = el.find(XS + "complexType")
        kids = None
        if anon is not None:
            kids = self.complex_children(anon, depth + 1, seen)
        elif t in self.types and t not in seen:
            kids = self.type_children(t, depth + 1, seen)
        if kids:
            node["k"] = {"c": kids}
        return node

    def op_tree(self, op):
        el = self.elements.get(op)
        if el is None:
            return None
        t = local(el.get("type"))
        kids = self.type_children(t, 0, set())
        return {"c": kids or []}


def collect_types(children, acc):
    for c in children:
        if "t" in c:
            acc.add(c["t"])
        if "k" in c:
            collect_types(c["k"]["c"], acc)


def main(root):
    versions = sorted(
        (d for d in os.listdir(root)
         if os.path.exists(os.path.join(root, d, "AXLSoap.xsd")) and d[0].isdigit()),
        key=lambda s: tuple(int(x) for x in s.split(".")))
    schemas = {v: Schema(os.path.join(root, v)) for v in versions}
    ops = [f"{p}{o}" for o in OBJECTS for p in ("add", "update", "remove")] + EXTRA_OPS
    result = {"versions": versions, "trees": {}, "enums": {}}
    types = set()
    for v in versions:
        tree = {}
        for op in ops:
            node = schemas[v].op_tree(op)
            if node is not None:
                tree[op] = node
                collect_types(node["c"], types)
        result["trees"][v] = tree
    for op in ops:
        if not any(op in t for t in result["trees"].values()):
            print("missing op:", op)
    for t in sorted(types):
        for v in reversed(versions):
            vals = schemas[v].enum_values(t)
            if vals:
                result["enums"][t] = vals
                break
    out = os.path.join(os.path.dirname(__file__), "..", "cucm_deployer", "axl_schema.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, separators=(",", ":"))
    print(f"wrote {out}: {len(ops)} ops x {len(versions)} versions, {len(result['enums'])} enums, "
          f"{os.path.getsize(out) // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1])
