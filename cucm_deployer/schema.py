"""AXL schema knowledge (element order, version support, defaults, enums).

axl_schema.json is generated from Cisco's AXL XSDs by tools/build_schema_map.py
and holds one element tree per AXL version (8.5 ... 12.5). CUCM validates
requests against its XSD, so child elements must be sent in that version's
order and only fields that exist in that version may be sent.
`AxlSchema.shape()` does both for any request dict.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(HERE, "axl_schema.json")


def vkey(version):
    """'12.5' -> (12, 5); '15' -> (15, 0)."""
    parts = [int(p) for p in str(version).split(".")[:2] if p.isdigit()]
    return tuple(parts + [0] * (2 - len(parts)))


class AxlSchema:
    def __init__(self, path=SCHEMA_FILE):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.versions = data["versions"]
        self.trees = data["trees"]
        self.enums = data["enums"]

    # ------------------------------------------------------------------
    def schema_version(self, axl_version):
        """Newest bundled schema not newer than the cluster's AXL version.
        Clusters newer than the bundled schemas (14.x, 15.x) use the newest one."""
        target = vkey(axl_version)
        best = self.versions[0]
        for v in self.versions:
            if vkey(v) <= target:
                best = v
        return best

    def is_newer_than_schema(self, axl_version):
        return vkey(axl_version) > vkey(self.versions[-1])

    def tree(self, op, axl_version):
        return self.trees[self.schema_version(axl_version)].get(op)

    def op_supported(self, op, axl_version):
        return self.tree(op, axl_version) is not None

    def top_fields(self, op, axl_version=None):
        """Names of the top-level elements of a request (update: key + fields)."""
        node = self.tree(op, axl_version or self.versions[-1])
        return [c["n"] for c in node["c"]] if node else []

    def object_fields(self, op, axl_version=None):
        """Top-level fields of the object inside an add request (addCss -> css.*)."""
        node = self.tree(op, axl_version or self.versions[-1])
        if not node or not node["c"]:
            return []
        return node["c"][0].get("k", {}).get("c", []) if op.startswith("add") else node["c"]

    def enum_for(self, op, path):
        """Enum values for a dotted field path of an add request object, or None."""
        children = self.object_fields(op)
        node = None
        for part in path.split("."):
            node = next((c for c in children if c["n"] == part), None)
            if node is None:
                return None
            children = node.get("k", {}).get("c", [])
        return self.enums.get(node.get("t")) if node else None

    def _exists_elsewhere(self, op, path, name):
        """Is path+name a field of this op in any bundled AXL version?"""
        for tree in self.trees.values():
            node = tree.get(op)
            children = node["c"] if node else []
            for part in [p for p in path.split(".") if p] + [name]:
                hit = next((c for c in children if c["n"] == part), None)
                if hit is None:
                    break
                children = hit.get("k", {}).get("c", [])
            else:
                return True
        return False

    # ------------------------------------------------------------------
    def shape(self, op, body, axl_version, fill_required=True):
        """Return (ordered_body, warnings) for an AXL request body.

        * children are re-ordered to the XSD sequence of this AXL version
        * fields that do not exist in this AXL version are dropped (warning)
        * unknown fields are dropped, or kept at the end for clusters newer
          than the bundled schema (their XSD may have them)
        * required fields that are missing get the XSD default or an empty
          (nil) element, like a WSDL-based client would send (inside the
          object for add, inside nested groups for update)
        """
        node = self.tree(op, axl_version)
        warnings = []
        if node is None:
            return body, [f"{op}: not in bundled schema - sent unchanged"]
        ctx = {
            "op": op,
            "lenient": self.is_newer_than_schema(axl_version),
            "ver": axl_version,
            "fill": fill_required and not op.startswith(("remove", "get", "list")),
            "warn": warnings,
        }
        return self._children(body, node["c"], ctx, "", top=True), warnings

    def _children(self, value, children, ctx, path, top=False):
        out = {}
        for k, v in value.items():
            if k.startswith("@"):
                out[k] = v
        names = set()
        for c in children:
            name = c["n"]
            names.add(name)
            if name in value:
                if value[name] is None:
                    continue
                out[name] = self._value(value[name], c, ctx, f"{path}{name}.")
            elif ctx["fill"] and c.get("r") and not top:
                if "d" in c:
                    out[name] = c["d"]
                elif c.get("z"):
                    out[name] = ""
        for k, v in value.items():
            if k.startswith("@") or k in names or v is None:
                continue
            if ctx["lenient"]:
                out[k] = v
                ctx["warn"].append(f"'{path}{k}' is not in the bundled schema - sent as-is")
            elif self._exists_elsewhere(ctx["op"], path, k):
                ctx["warn"].append(f"'{path}{k}' is not available in AXL {ctx['ver']} - skipped")
            else:
                ctx["warn"].append(f"'{path}{k}' is not a valid AXL field - skipped")
        return out

    def _value(self, v, node, ctx, path):
        if isinstance(v, list):
            return [self._value(i, node, ctx, path) for i in v]
        if isinstance(v, dict) and "k" in node:
            return self._children(v, node["k"]["c"], ctx, path)
        return v


_schema = None


def get_schema():
    global _schema
    if _schema is None:
        _schema = AxlSchema()
    return _schema
