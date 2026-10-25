#!/usr/bin/env python3
"""
extract_components.py - list the components in a DesignSpark PCB schematic file.

DesignSpark PCB saves designs as an OLE2 "compound document" (even when the
file is named .hex, .asc, etc.). The design lives in a stream called
"Contents" which is a serialised C++ object graph. This script reads that
stream directly (no third-party libraries needed - pure standard library) and
pulls out, for every component instance:

    RefDes     e.g. C1, R6, U1
    Type       component name / package (see --type-source)
    Value      e.g. 0.1uF, 47k (blank if the part has no value)
    Footprint  the PCB footprint (decal) name
    Component  the library component name

Usage:
    python3 extract_components.py design.hex                 -> design_components.csv
    python3 extract_components.py design.hex -o parts.txt --format txt
    python3 extract_components.py a.hex b.hex c.hex          -> one output per input
    python3 extract_components.py design.hex --format txt -o -   (print to screen)

Options:
    --format csv|txt        csv (default) or "C1, 0805, 0.1uF" style text lines
    --type-source auto|component|footprint
                            What goes in the Type column (default: auto).
                            auto      = library component name, except when that
                                        name is just a generic package name
                                        (e.g. C805/R805) - then use the footprint
                                        (0805).
    --include-power         also list power/ground symbols (REF1, REF2 ...)
    --report                grouped parts list instead: identical type+value are
                            combined with a count, e.g.
                                R1, R2, R3 | 3 off | 22k | 0805
                            (written to <input>_report.csv / .txt)
"""
import argparse
import csv
import os
import re
import struct
import sys

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
FREE = 0xFFFFFFFA  # sector ids >= this are special markers


# --------------------------------------------------------------------------
# Minimal OLE2 (Microsoft compound file) reader
# --------------------------------------------------------------------------
class OLE:
    def __init__(self, data):
        if data[:8] != OLE_MAGIC:
            raise ValueError("not an OLE2 compound file (is this a DesignSpark PCB file?)")
        self.d = data
        self.ss = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mss = 1 << struct.unpack_from("<H", data, 32)[0]
        nfat, dirstart, _, cutoff, minifat, nmini, difat, ndifat = struct.unpack_from(
            "<I4xIIIIIII", data, 44)
        self.cutoff = cutoff
        sect = list(struct.unpack_from("<109I", data, 76))
        while difat < FREE and ndifat:
            v = struct.unpack("<%dI" % (self.ss // 4), self._sec(difat))
            sect += v[:-1]
            difat = v[-1]
            ndifat -= 1
        sect = [s for s in sect if s < FREE][:nfat]
        self.fat = []
        for s in sect:
            self.fat += struct.unpack("<%dI" % (self.ss // 4), self._sec(s))
        self.mfat = []
        if nmini and minifat < FREE:
            mb = self._chain(minifat)
            self.mfat = list(struct.unpack("<%dI" % (len(mb) // 4), mb))
        dirb = self._chain(dirstart)
        self.entries = []
        for i in range(len(dirb) // 128):
            e = dirb[i * 128:(i + 1) * 128]
            nl = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(nl - 2, 0)].decode("utf-16le", "replace")
            start, size = struct.unpack_from("<IQ", e, 116)
            self.entries.append((name, e[66], start, size))
        root = self.entries[0]
        self.ministream = (self._chain(root[2])[:root[3]] if root[2] < FREE else b"")

    def _sec(self, i):
        return self.d[512 + i * self.ss:512 + (i + 1) * self.ss]

    def _chain(self, i):
        out, seen = [], set()
        while i < FREE and i not in seen:
            seen.add(i)
            out.append(self._sec(i))
            i = self.fat[i]
        return b"".join(out)

    def stream(self, wanted):
        for name, typ, start, size in self.entries:
            if typ == 2 and name == wanted:
                if size < self.cutoff:
                    out, i = [], start
                    while i < FREE:
                        out.append(self.ministream[i * self.mss:(i + 1) * self.mss])
                        i = self.mfat[i]
                    return b"".join(out)[:size]
                return self._chain(start)[:size]
        raise KeyError(wanted)


# --------------------------------------------------------------------------
# Parsing of the "Contents" stream
# --------------------------------------------------------------------------
def lpstr(c, i):
    """Length-prefixed (1 byte) printable-ASCII string at offset i -> (text, next_offset)."""
    if i >= len(c):
        return None, i
    n = c[i]
    if 1 <= n <= 120 and i + 1 + n <= len(c) and all(32 <= x < 127 for x in c[i + 1:i + 1 + n]):
        return c[i + 1:i + 1 + n].decode("ascii"), i + 1 + n
    return None, i


# The serialised format numbers its objects/classes per file, so the 2-byte tags
# that mark things (instance tag, "value" attribute id, class tags) differ from
# file to file.  They are learned from the data rather than hard-coded.
REF_RE = re.compile(rb"([\x02-\x08])([A-Za-z]{1,4}[0-9]{1,5})([\x00-\xff][\x80-\xff])")
VALUE_RE = re.compile(rb"(..)([\x01-\x40])([\x20-\x7e]+)\x01\x00\x00(..)\x00\x00", re.S)
YI_RE = re.compile(rb"([\x00-\xff][\x80-\xff])yi\x00", re.S)


def learn_tags(c):
    """Return (instance_tag, value_tag, decal_marker) as 2-byte strings (None if not found)."""
    from collections import Counter
    inst = Counter(m.group(3) for m in REF_RE.finditer(c) if m.group(1)[0] == len(m.group(2)))
    inst_tag = inst.most_common(1)[0][0] if inst else b"\xd2\x84"
    vt = Counter()
    for m in VALUE_RE.finditer(c):
        if m.group(2)[0] == len(m.group(3)):
            w = int.from_bytes(m.group(1), "little")
            if int.from_bytes(m.group(4), "little") == w - 1:
                vt[m.group(1)] += 1
    value_tag = vt.most_common(1)[0][0] if vt else b"\x98\x04"
    decal_mark = (int.from_bytes(value_tag, "little") - 1).to_bytes(2, "little")
    return inst_tag, value_tag, decal_mark


def parse_components(c):
    inst_tag, value_tag, decal_mark = learn_tags(c)
    DECAL_MARK = decal_mark + b"\x00\x00"
    VALUE = re.compile(re.escape(value_tag) + rb"([\x00-\x40])")
    ANCHOR = re.compile(rb"([\x02-\x08])([A-Za-z]{1,4}[0-9]{1,5})(?:" + re.escape(inst_tag) + rb"|\xff\xff)")

    anchors = [m for m in ANCHOR.finditer(c) if m.group(1)[0] == len(m.group(2))]

    shared = {}          # footprint-object id -> (footprint, component name)
    parts = []
    prev = 0
    for m in anchors:
        a = m.start()
        ref = m.group(2).decode()
        seg = c[prev:a]

        # ---- value: last "<value tag> <len> <text>" in this record that is followed by the footprint marker
        value = ""
        for vm in VALUE.finditer(seg):
            n = vm.group(1)[0]
            tail = seg[vm.end() + n: vm.end() + n + 10]
            if DECAL_MARK in tail:
                value = seg[vm.end():vm.end() + n].decode("latin1")

        footprint = comp = None
        inline = c[a - 6:a] == b"\x00" * 6 and b".cml" in c[a - 40:a]
        if inline:
            # first instance of this part type: footprint + component are defined here
            yis = list(YI_RE.finditer(seg))
            did = None
            for ym in yis:   # the last object that is followed by a real (non-zero) id
                idm = re.match(rb"\x00(..)", seg[ym.end():ym.end() + 3], re.S)
                if idm and 0x100 <= int.from_bytes(idm.group(1), "little") < 0x8000:
                    did = int.from_bytes(idm.group(1), "little")
            for pm in re.finditer(re.escape(DECAL_MARK), seg):
                s1, j = lpstr(c, prev + pm.end())
                if s1:
                    s2, _ = lpstr(c, j)
                    if s2:
                        footprint = s2
            names = []
            if yis and len(seg) - yis[-1].end() < 600:
                j = prev + yis[-1].end()
                while j < a and c[j] == 0:
                    j += 1
                while j < a:
                    s, j2 = lpstr(c, j)
                    if s is None:
                        break
                    names.append(s)
                    j = j2
            comp = names[-1] if names else None
            if footprint is None:   # fallback (e.g. parts defined in the symbol section)
                for fm in re.finditer(rb"\x04(?:USER|DSCV)", seg):
                    s2, _ = lpstr(c, prev + fm.end())
                    if s2:
                        footprint = s2
            if comp is None:        # fallback: schematic component name
                sm = re.search(rb"CScmComponent[^\x00]{0,4}\x00*", seg)
                if sm:
                    comp, _ = lpstr(c, prev + sm.end())
            if did is not None:
                shared[did] = (footprint, comp)
        else:
            tid = int.from_bytes(c[a - 2:a], "little")
            footprint, comp = shared.get(tid, (None, None))

        parts.append({"ref": ref, "value": value, "footprint": footprint or "", "component": comp or ""})
        prev = a
    return parts


def choose_type(p, source):
    comp, fp = p["component"], p["footprint"]
    if source == "component":
        return comp or fp
    if source == "footprint":
        return fp or comp
    # auto: if the component name is just "<letters><package name>", e.g. C805 / R805 / R1206_TOP,
    # the footprint is the more meaningful description.
    if comp and fp and comp != fp:
        rest = comp[1:]
        # keep names that already contain the whole footprint (R1206_TOP); only
        # abbreviated package names (C805 for 0805) are replaced by the footprint
        if fp not in comp and rest and rest in fp:
            return fp
    return comp or fp


def natural_key(ref):
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1).upper(), int(m.group(2))) if m else (ref, 0)


def group_parts(parts):
    """Group parts with the same type and value -> list of (refs, count, value, type)."""
    groups = {}
    for p in parts:
        groups.setdefault((p["type"], p["value"]), []).append(p["ref"])
    rows = []
    for (typ, val), refs in groups.items():
        refs.sort(key=natural_key)
        rows.append((refs, len(refs), val, typ))
    rows.sort(key=lambda r: natural_key(r[0][0]))
    return rows


def read_design(path):
    with open(path, "rb") as f:
        data = f.read()
    return OLE(data).stream("Contents")


def main():
    ap = argparse.ArgumentParser(description="Extract a component list from a DesignSpark PCB file.")
    ap.add_argument("files", nargs="+", help="input design file(s)")
    ap.add_argument("-o", "--output", help="output path ('-' for screen). Only valid with one input file.")
    ap.add_argument("--format", choices=["csv", "txt"], default="csv")
    ap.add_argument("--type-source", choices=["auto", "component", "footprint"], default="auto")
    ap.add_argument("--report", action="store_true",
                    help="group identical type+value parts with a count (BOM-style)")
    ap.add_argument("--include-power", action="store_true", help="include power/ground symbols (REFn)")
    args = ap.parse_args()
    if args.output and len(args.files) > 1:
        ap.error("-o can only be used with a single input file")

    for path in args.files:
        try:
            parts = parse_components(read_design(path))
        except Exception as e:  # noqa: BLE001
            print("%s: %s" % (path, e), file=sys.stderr)
            continue
        if not args.include_power:
            parts = [p for p in parts if not p["ref"].upper().startswith("REF")]
        parts.sort(key=lambda p: natural_key(p["ref"]))
        for p in parts:
            p["type"] = choose_type(p, args.type_source)

        suffix = "_report." if args.report else "_components."
        out = args.output or (os.path.splitext(path)[0] + suffix + args.format)
        fh = sys.stdout if out == "-" else open(out, "w", newline="", encoding="utf-8")
        try:
            if args.report:
                rows = group_parts(parts)
                if args.format == "csv":
                    w = csv.writer(fh)
                    w.writerow(["RefDes", "Qty", "Value", "Type"])
                    for refs, n, val, typ in rows:
                        w.writerow([", ".join(refs), n, val, typ])
                else:
                    rw = max(len(", ".join(r[0])) for r in rows) if rows else 0
                    vw = max([len(r[2]) for r in rows] + [0])
                    for refs, n, val, typ in rows:
                        fh.write("%s , %-6s , %s , %s\n" % (
                            ", ".join(refs).ljust(rw), "%d off" % n, val.ljust(vw), typ))
            elif args.format == "csv":
                w = csv.writer(fh)
                w.writerow(["RefDes", "Type", "Value", "Footprint", "Component"])
                for p in parts:
                    w.writerow([p["ref"], p["type"], p["value"], p["footprint"], p["component"]])
            else:
                for p in parts:
                    fh.write(", ".join(x for x in (p["ref"], p["type"], p["value"]) if x) + "\n")
        finally:
            if fh is not sys.stdout:
                fh.close()
        if out != "-":
            print("%s: %d components -> %s" % (path, len(parts), out))


if __name__ == "__main__":
    main()
