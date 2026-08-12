# Hardware Components

Symbols, footprints, 3D models and datasheets for every electronics component
used in the group, kept in one place and generated into KiCad libraries on
demand.

The source layout is one folder per part, so a datasheet lives next to the
symbol that describes it. KiCad cannot consume that layout directly — it wants
a single `.kicad_sym` file per library and a directory whose name ends in
`.pretty` — so `build_kicad_libs.py` derives the KiCad-shaped libraries from it.
`build/` is generated and gitignored; **it does not exist in a fresh clone.**

---

## First-time setup

### 1. Clone and build

```bash
git clone <repo-url> ~/Libs/electronicsComponents
cd ~/Libs/electronicsComponents

# kicad-cli normalises the file format before merging. Symbol files in this
# repo span three format versions (20211014 / 20231120 / 20241209) and mixing
# them in one library can leave stale constructs behind.
export PATH="/Applications/KiCad/KiCad.app/Contents/MacOS:$PATH"   # macOS
# export PATH="/usr/lib/kicad/bin:$PATH"                           # Linux

python3 build_kicad_libs.py --upgrade
```

Expected output:

```
29 symbols, 45 footprints, 39 3D models -> .../build
25 symbol->footprint links repaired, 2 hand-set defaults kept

1 item(s) need attention:
  - R: no default footprint, candidates ['R_0603', 'R_0805'] - ...
```

That single item is intentional; see [Known state](#known-state).

If `kicad-cli` is not on `PATH` the script prints a warning and merges anyway.
That usually still loads, but prefer `--upgrade`.

### 2. Define the two path variables

KiCad → **Settings → Configure Paths → Environment Variables**:

| Name | Value |
| --- | --- |
| `AA_LIB` | `/absolute/path/to/electronicsComponents/build` |
| `AA_3DMODELS` | `/absolute/path/to/electronicsComponents/build/AA.3dshapes` |

Absolute paths only — KiCad does not expand `~`.

### 3. Register the libraries

Either add the entries by hand in **Preferences → Manage Symbol Libraries →
Global** (and again under Manage Footprint Libraries), or paste the generated
tables, which is faster:

```bash
# macOS, KiCad 9:   ~/Library/Preferences/kicad/9.0
# Linux, KiCad 9:   ~/.config/kicad/9.0
cd ~/Library/Preferences/kicad/9.0
cp sym-lib-table sym-lib-table.orig
cp fp-lib-table  fp-lib-table.orig
```

**Quit KiCad first** — it rewrites these files on exit and will discard your
edits. Then copy the `(lib …)` lines from `build/sym-lib-table` and
`build/fp-lib-table` into the corresponding files, before the closing `)`. If
yours are otherwise empty, copy the generated files over wholesale.

### 4. Verify

Restart KiCad and open the Symbol Editor. Six libraries should appear at the
top of the list:

`AA_active` · `AA_passive` · `AA_connectors` · `AA_photoelectronics` ·
`AA_mechanics` · `AA_devices`

Place a `TL071H` in a schematic and check that its Footprint field is already
`AA_active:TL071H`. Open the 3D viewer on a board containing it to confirm the
STEP model resolves.

The `AA_` prefix exists so these sort above KiCad's stock libraries in the
chooser. Change `PREFIX` at the top of both scripts to rename them — it must
match in both.

---

## Adding a part

Create a folder under the right category and drop the files in, named after the
part:

```
passive/LMV321/
    LMV321.kicad_sym        symbol
    LMV321.kicad_mod        footprint  (several allowed: LMV321_SOIC, LMV321_DIP)
    LMV321.step             3D model, named to match the footprint
    LMV321.pdf              datasheet
```

Then:

```bash
./fix_components.sh          # dry run - shows what it would change
./fix_components.sh --apply
python3 build_kicad_libs.py --upgrade
```

KiCad caches libraries. After a rebuild, open **Preferences → Manage Symbol
Libraries → OK**, or restart, to pick up the changes.

### Naming rules the scripts rely on

- The 3D model file must be named after the **footprint**, not the vendor part
  number. `LMV321_SOIC.kicad_mod` pairs with `LMV321_SOIC.step`.
- If a folder holds exactly one footprint, symbols in it link to it
  automatically. With several, the symbol is linked only when a footprint's
  name matches the symbol's; otherwise set the Footprint property yourself and
  the build script will leave it alone.
- Name the symbol after the part, not the order code. `fix_components.sh` has a
  `RENAMES` table for the ones already in the repo; add an entry there when a
  vendor download brings in another.

Before drawing something from scratch, check whether KiCad already ships it —
`/Applications/KiCad/KiCad.app/Contents/SharedSupport/` on macOS,
`/usr/share/kicad/` or `/snap/kicad/current/usr/share/kicad/` on Linux.

---

## The two scripts

### `fix_components.sh`

Repairs the source tree. Dry run by default, `--apply` to write; refuses to run
on a dirty git tree. Idempotent.

- normalises CRLF to LF (vendor exports are CRLF, KiCad's own files are LF)
- renames vendor order codes to readable symbol names, keeping the MPN in
  `Description` so the chooser still finds it by part number
- repoints stale `(model …)` paths at the sibling model file, and inserts a
  model block into footprints that have a model file but no reference to it
- anchors the Raspberry Pi Pico footprints at `${KICAD9_3DMODEL_DIR}`
- sets a default footprint for multi-variant parts
- deletes legacy `.lib` / `.dcm` / `.mod` / `.bak` / `.DS_Store` and the symbol
  files that duplicate libraries shipped with KiCad

### `build_kicad_libs.py`

Generates `build/` — merged symbol libraries, `.pretty` footprint directories,
a shared `AA.3dshapes/`, and ready-to-paste library tables. Never writes outside
`build/`.

```bash
python3 build_kicad_libs.py --check      # report only, writes nothing
python3 build_kicad_libs.py --upgrade    # normalise formats, then build
```

`load_components.sh` and `load_list_of_components.py` are the earlier
copy-everything-into-one-folder approach and are superseded by these.

---

## Known state

- **`R` has no default footprint, by design.** A generic resistor should be
  assigned per placement. Uncomment the last line of section 3 in
  `fix_components.sh` to default it to 0603.
- **`ESD9B5-0ST5G-L` and `-M` share the base variant's STEP.** No
  variant-specific model exists, so the 3D view is approximate — adequate for
  clearance checking, not for a mechanical fit-up against a housing.
- **`LMC555.kicad_sym` was a byte-copy of `LM555.kicad_sym`.** Both 555s share a
  pinout so the graphics are valid, but confirm the part before trusting it.
- **`STM32G473CBT6` keeps its MPN as the symbol name**, deliberately — it reads
  better on a schematic than the folder name `STM32G4-73CBT6-LQFP48`.

---

## Gotchas

**Renaming a symbol breaks existing schematics.** Schematics store
`LibNick:SymbolName`. Run `fix_components.sh --apply` before placing parts from
these libraries, not after.

**`*.mod` also matches `*.kicad_mod`.** The cruft-deletion `find` in
`fix_components.sh` carries an explicit `-not -name '*.kicad_mod'`. Without it,
every footprint in the repo would be deleted. Do not remove that guard.

**Large binaries belong in git-LFS.** Datasheets and STEP files dominate the
pack. Before adding more:

```bash
git lfs migrate import --include="*.pdf,*.step,*.stp,*.wrl,*.igs" --everything
```

A `.gitattributes` containing `*.kicad_* text eol=lf` keeps vendor downloads
from reintroducing CRLF churn.

**Do not vendor libraries that ship with KiCad.** Stock symbols shadow the real
ones and drift on the next release. Custom short-named *footprints* such as
`C_0603` and `R_0805` are fine to keep; use `Device:C` for the symbol and pair
it with `AA_passive:C_0603`.
