# DesignSpark PCB Component Extractor

A small, dependency-free Python script that pulls a parts list (bill of materials) out of
DesignSpark PCB .sch design files.

It reads the design file directly and lists every component with its reference, type and
value. It can also produce a grouped, BOM-style report with quantities.

> **Not affiliated with DesignSpark, RS Components or Advanced Circuits.** This is an
> independent tool that reads your own design files. It was built by inspecting the file
> format, which is undocumented, so it may not work with every version of the program.

## Features

- Pure Python 3 standard library: nothing to install
- Works on DesignSpark PCB schematic (`.sch`) files, including ones saved with another
  extension (any OLE2 compound document containing a `Contents` stream)
- PCB layout (`.pcb`) files are not supported
- Outputs CSV (opens in Excel / LibreOffice) or plain text
- `--report` groups identical parts and counts them, e.g. `R1, R2, R3 , 3 off , 22k , 0805`
- Handles several files in one run

## Requirements

Python 3.6 or later.

## Usage

```
python3 extract_components.py design.sch
```

This writes `design_components.csv` next to the input file.

### Examples

```
# CSV list of every component
python3 extract_components.py design.sch

# Text list: "C1, 0805, 0.1uF"
python3 extract_components.py design.sch --format txt

# Grouped report with counts
python3 extract_components.py design.sch --report --format txt

# Print to the screen instead of writing a file
python3 extract_components.py design.sch --report --format txt -o -

# Several files at once (one output file per input)
python3 extract_components.py a.sch b.sch c.sch
```

### Options

| Option | Description |
|---|---|
| `-o`, `--output PATH` | Output file (`-` prints to the screen). Single input file only. |
| `--format csv\|txt` | Output format. Default `csv`. |
| `--report` | Group parts with the same type and value, with a count. |
| `--type-source auto\|component\|footprint` | What goes in the *Type* column (see below). Default `auto`. |
| `--include-power` | Also list power/ground symbols (`REF1`, `REF2`, ...), which are hidden by default. |

### Output

**Component list** (CSV columns): `RefDes, Type, Value, Footprint, Component`

```
C1,0805,0.1uF,0805,C805
R3,0805,10K,0805,R805
U2,MCP6002_DIP,,8DIL,MCP6002_DIP
```

**Report** (`--report --format txt`):

```
C1, C2, C3, C4, C5, C6 , 6 off  , 0.1uF , 0805
R1                     , 1 off  , 1K    , 0805
R3, R4                 , 2 off  , 10K   , 0805
U2                     , 1 off  ,       , MCP6002_DIP
```

The report columns are: references, quantity, value, type. With CSV the columns are
`RefDes, Qty, Value, Type`. Parts with no value are grouped together with a blank value.

### What is "Type"?

Each part has a library **component name** (e.g. `R805`, `IRLM0040TRPBF_TOP`) and a PCB
**footprint** (e.g. `0805`, `SOT-23_TOP`). With `--type-source auto` (the default):

- the component name is used, **except**
- where the component name is just an abbreviated package name (e.g. `C805` or `R805` for the
  `0805` footprint), in which case the footprint is used.

Use `--type-source component` or `--type-source footprint` to force one or the other. Both
values are always available in the CSV `Footprint` and `Component` columns.

## How it works

DesignSpark PCB saves designs as a Microsoft OLE2 compound document. The design is held in a
stream called `Contents`, which is a serialised object graph. The script:

1. Reads the compound document with a small built-in OLE2 reader.
2. Learns the file's internal tag numbers from the data (these differ from file to file).
3. Finds each component instance and reads its reference, value and shared footprint /
   library component definition.

## Limitations

- Developed and tested against only two design files, saved by DesignSpark PCB (v12.0-era
  libraries). Other versions may store things differently.
- The file format is undocumented and was worked out by inspection, so edge cases are likely
  (unusual part definitions, very large designs, very old files).
- Only reference, value, footprint and library component name are extracted. Other part
  attributes (manufacturer, part numbers, etc.) are not read.
- Power/ground symbols are identified by the reference prefix `REF`.
- Read-only: the script never modifies your design file.

## Contributing

If a file gives missing or wrong parts, please open an issue and, if you can, attach the file
(or a cut-down design that shows the problem) along with the version of DesignSpark PCB that
saved it.

## Licence

[BSD Zero Clause Licence (0BSD)](LICENSE). You can use, copy, modify and distribute this
software for any purpose, with or without fee, and without any attribution requirement.
