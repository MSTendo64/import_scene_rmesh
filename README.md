# RMesh Importer

A Blender add-on for importing SCP: Containment Breach `.rmesh` room meshes.

## Installation

1. Download this repository as a ZIP archive.
2. In Blender, open **Edit → Preferences → Add-ons → Install from Disk**.
3. Select the ZIP archive and enable **RMesh Importer**.
4. Use **File → Import → RMesh (.rmesh)**.

## Dependencies

The importer uses only Blender's Python API and the Python standard library. No
third-party Python packages are required. In particular, the binary reader is
implemented directly with `struct`, `io`, and `pathlib`; Kaitai Struct and
`kaitaistruct` are not used.

## Import options

- **Import Materials** creates materials and loads matching image files from
  the directory containing the RMesh file. Missing or unreadable textures are
  reported as warnings; geometry import continues.
- **Import Entities as empties** creates an entity hierarchy and imports the
  supported point entities as Blender empties.
- **Import Scale** converts the game's large world-coordinate units to Blender
  units. The default `0.00625` matches the scale used by established SCP-CB
  Blender tooling; use `0.00390625` for the documented in-game scale, or adjust
  it to suit your scene. The scale is applied to mesh vertices and entity
  positions (not model-local scale values).

Mesh vertices are converted from the source coordinate order to Blender's
coordinate order. Both UV sets (`uv1` and `uv2`) are preserved.

## Format handling

The reader validates input lengths, string sizes, collection counts, UTF-8
strings, and finite floating-point values. Invalid or truncated files produce
a readable import error instead of an uncontrolled parser exception.

## License

SCP: Containment Breach, its source code, and the original add-on source are
licensed under Creative Commons Attribution-ShareAlike 3.0
(CC BY-SA 3.0): http://creativecommons.org/licenses/by-sa/3.0/
