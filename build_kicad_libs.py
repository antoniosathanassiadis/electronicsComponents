#!/usr/bin/env python3
"""
Build proper KiCad libraries from the per-part folder layout.

Source layout (authoring, one folder per part, datasheets alongside):
    <category>/[<subcategory>/]<Part>/<Part>.kicad_sym
                                     <Part>*.kicad_mod
                                     <Part>*.step | .wrl

Output layout (what KiCad actually consumes):
    build/AA_<category>.kicad_sym     one symbol lib per top-level category
    build/AA_<category>.pretty/       footprint lib (dir name MUST end in .pretty)
    build/AA.3dshapes/                one shared 3D model dir
    build/sym-lib-table  fp-lib-table  ready-to-paste library tables

While merging it also repairs the two things that are broken repo-wide:
  * symbol "Footprint" properties -> "AA_<category>:<FootprintName>"
  * footprint (model ...) paths   -> "${AA_3DMODELS}/<file>"

Usage:
    python3 build_kicad_libs.py                 # build
    python3 build_kicad_libs.py --upgrade       # normalise formats via kicad-cli first
    python3 build_kicad_libs.py --check         # report only, write nothing
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

PREFIX = "AA"                      # library nickname prefix, sorts to top of the picker
ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
MODEL_VAR = f"${{{PREFIX}_3DMODELS}}"   # ${AA_3DMODELS}
LIB_VAR = f"{PREFIX}_LIB"               # env var pointing at build/

CATEGORIES = ["active", "passive", "connectors", "photoelectronics",
              "mechanics", "devices"]

# Symbol files that are verbatim copies of libraries shipped with KiCad.
# Keeping them shadows the stock libs and guarantees drift on the next release.
VENDORED_STOCK = {
    "C.kicad_sym",                 # 533 symbols == Device.kicad_sym capacitors
    "LED.kicad_sym",               # 63 symbols  == Device.kicad_sym LEDs
    "RaspberryPi_Pico.kicad_sym",  # 12 symbols  == MCU_Module.kicad_sym
}

MODEL_EXT = (".step", ".stp", ".wrl", ".igs")
SYM_HEADER = '(kicad_symbol_lib (version 20241209) (generator "build_kicad_libs")'


# --------------------------------------------------------------------------
# minimal s-expression handling
# --------------------------------------------------------------------------

def top_level_blocks(text: str) -> list[str]:
    """Return the direct children of the outermost s-expression."""
    try:
        start_root = text.index("(")
    except ValueError:
        return []
    depth, in_str, esc, start = 0, False, False, None
    out: list[str] = []
    for j in range(start_root, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:
                start = j
        elif c == ")":
            if depth == 2 and start is not None:
                out.append(text[start:j + 1])
                start = None
            depth -= 1
            if depth == 0:
                break
    return out


SYM_NAME_RE = re.compile(r'\(\s*symbol\s+"((?:[^"\\]|\\.)*)"')
FP_PROP_RE = re.compile(r'(\(\s*property\s+"Footprint"\s+)"(?:[^"\\]|\\.)*"')
MODEL_RE = re.compile(r'(\(\s*model\s+)"((?:[^"\\]|\\.)*)"')


def symbol_name(block: str) -> str | None:
    m = SYM_NAME_RE.match(block.strip())
    return m.group(1) if m else None


def set_footprint(block: str, value: str) -> tuple[str, bool]:
    """Set the Footprint property; returns (block, changed)."""
    if FP_PROP_RE.search(block):
        new = FP_PROP_RE.sub(lambda m: f'{m.group(1)}"{value}"', block, count=1)
        return new, new != block
    # no Footprint property at all -> insert one after the Value property
    ins = block.find('(property "Value"')
    if ins == -1:
        return block, False
    close = _match_paren(block, block.index("(", ins))
    prop = (f'\n    (property "Footprint" "{value}" (at 0 0 0)\n'
            f'      (effects (font (size 1.27 1.27)) (hide yes))\n    )')
    return block[:close + 1] + prop + block[close + 1:], True


def _match_paren(text: str, i: int) -> int:
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
    return len(text) - 1


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

class Part:
    def __init__(self, folder: Path, category: str):
        self.folder = folder
        self.category = category
        self.syms = sorted(folder.glob("*.kicad_sym"))
        self.fps = sorted(folder.glob("*.kicad_mod"))
        self.models = sorted(p for p in folder.iterdir()
                             if p.suffix.lower() in MODEL_EXT)

    @property
    def rel(self) -> str:
        return str(self.folder.relative_to(ROOT))


def discover() -> list[Part]:
    parts: list[Part] = []
    for cat in CATEGORIES:
        cdir = ROOT / cat
        if not cdir.is_dir():
            continue
        for folder in sorted(p for p in cdir.rglob("*") if p.is_dir()):
            if "tests" in folder.parts or folder.name.startswith("."):
                continue
            part = Part(folder, cat)
            if part.syms or part.fps or part.models:
                parts.append(part)
    return parts


def pick_footprint(sym: str, fps: list[Path]) -> Path | None:
    """Choose the footprint a given symbol should link to."""
    if not fps:
        return None
    if len(fps) == 1:
        return fps[0]
    stems = {p.stem: p for p in fps}
    if sym in stems:
        return stems[sym]
    cands = [p for p in fps if p.stem.startswith(sym)]
    if len(cands) == 1:
        return cands[0]
    return None  # genuinely ambiguous -> report, do not guess


# --------------------------------------------------------------------------
# kicad-cli format normalisation (optional)
# --------------------------------------------------------------------------

def upgrade(path: Path, kind: str) -> Path:
    """Run `kicad-cli {sym,fp} upgrade` on a temp copy; return the copy."""
    tmp = Path(tempfile.mkdtemp()) / path.name
    if kind == "sym":
        shutil.copy2(path, tmp)
    else:
        shutil.copytree(path, tmp)
    try:
        subprocess.run(["kicad-cli", kind, "upgrade", str(tmp)],
                       check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return path
    return tmp


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upgrade", action="store_true",
                    help="normalise file formats with kicad-cli before merging")
    ap.add_argument("--check", action="store_true",
                    help="report problems, write nothing")
    args = ap.parse_args()

    if args.upgrade and shutil.which("kicad-cli") is None:
        print("!! kicad-cli not on PATH, skipping format normalisation\n")
        args.upgrade = False

    parts = discover()
    warn: list[str] = []
    stats = {"sym": 0, "fp": 0, "model": 0, "linked": 0}

    if not args.check:
        if BUILD.exists():
            shutil.rmtree(BUILD)
        (BUILD / f"{PREFIX}.3dshapes").mkdir(parents=True)

    # ---- 3D models: flat shared dir, first-wins on name collision -------
    model_names: dict[str, Path] = {}
    for part in parts:
        for m in part.models:
            if m.name in model_names and model_names[m.name] != m:
                warn.append(f"duplicate 3D model name {m.name} "
                            f"({model_names[m.name].parent.name} vs {part.folder.name})")
                continue
            model_names[m.name] = m
            if not args.check:
                shutil.copy2(m, BUILD / f"{PREFIX}.3dshapes" / m.name)
            stats["model"] += 1

    # ---- footprints: one .pretty per category ---------------------------
    fp_index: dict[str, str] = {}      # footprint stem -> library nickname
    for cat in CATEGORIES:
        nick = f"{PREFIX}_{cat}"
        pretty = BUILD / f"{nick}.pretty"
        cat_parts = [p for p in parts if p.category == cat and p.fps]
        if not cat_parts:
            continue
        if not args.check:
            pretty.mkdir(exist_ok=True)
        seen: dict[str, Path] = {}
        for part in cat_parts:
            for fp in part.fps:
                if fp.stem in seen:
                    warn.append(f"duplicate footprint name {fp.stem} in {nick} "
                                f"({seen[fp.stem].parent.name} vs {part.folder.name})")
                    continue
                seen[fp.stem] = fp
                fp_index[fp.stem] = nick
                text = fp.read_text(encoding="utf-8", errors="replace")

                local = {m.name: m for m in part.models}

                def fix(m: re.Match) -> str:
                    path = m.group(2)
                    base = path.replace("\\", "/").split("/")[-1]
                    if base in local or base in model_names:
                        return f'{m.group(1)}"{MODEL_VAR}/{base}"'
                    if path.startswith("${KICAD"):
                        return m.group(0)          # valid stock model, leave alone
                    warn.append(f"{fp.stem}: unresolved 3D model path {path}")
                    return m.group(0)

                text = MODEL_RE.sub(fix, text)

                # footprint has no model at all but the part folder ships one
                if "(model" not in text and part.models:
                    add = "\n  " + "\n  ".join(
                        f'(model "{MODEL_VAR}/{m.name}"\n'
                        f'    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0))\n  )'
                        for m in part.models)
                    close = text.rstrip().rfind(")")
                    text = text[:close] + add + "\n" + text[close:]
                    warn.append(f"{fp.stem}: added missing 3D model reference")

                if not args.check:
                    (pretty / fp.name).write_text(text, encoding="utf-8")
                stats["fp"] += 1
        if args.upgrade and not args.check:
            up = upgrade(pretty, "fp")
            if up != pretty:
                shutil.rmtree(pretty)
                shutil.copytree(up, pretty)

    # ---- symbols: one merged .kicad_sym per category --------------------
    for cat in CATEGORIES:
        nick = f"{PREFIX}_{cat}"
        blocks: list[str] = []
        names: dict[str, str] = {}
        for part in (p for p in parts if p.category == cat and p.syms):
            for symfile in part.syms:
                if symfile.name in VENDORED_STOCK:
                    warn.append(f"skipped {part.rel}/{symfile.name} "
                                f"(verbatim copy of a stock KiCad library)")
                    continue
                src = upgrade(symfile, "sym") if args.upgrade else symfile
                text = src.read_text(encoding="utf-8", errors="replace")
                for blk in top_level_blocks(text):
                    if not blk.lstrip().startswith("(symbol"):
                        continue
                    name = symbol_name(blk)
                    if name is None:
                        continue
                    if name in names:
                        warn.append(f"duplicate symbol {name} in {nick} "
                                    f"({names[name]} vs {part.rel})")
                        continue
                    names[name] = part.rel

                    fp = pick_footprint(name, part.fps)
                    if fp is not None:
                        blk, changed = set_footprint(
                            blk, f"{fp_index.get(fp.stem, nick)}:{fp.stem}")
                        if changed:
                            stats["linked"] += 1
                    elif part.fps:
                        warn.append(f"{name}: ambiguous footprint, candidates "
                                    f"{[p.stem for p in part.fps]}")
                    else:
                        warn.append(f"{name}: no footprint in {part.rel}")
                    blocks.append(blk)
                    stats["sym"] += 1
        if blocks and not args.check:
            body = "\n".join("  " + b.replace("\n", "\n  ") for b in blocks)
            (BUILD / f"{nick}.kicad_sym").write_text(
                f"{SYM_HEADER}\n{body}\n)\n", encoding="utf-8")

    # ---- library tables --------------------------------------------------
    if not args.check:
        syms, fps = [], []
        for cat in CATEGORIES:
            nick = f"{PREFIX}_{cat}"
            if (BUILD / f"{nick}.kicad_sym").exists():
                syms.append(f'  (lib (name "{nick}")(type "KiCad")'
                            f'(uri "${{{LIB_VAR}}}/{nick}.kicad_sym")'
                            f'(options "")(descr "{cat} symbols"))')
            if (BUILD / f"{nick}.pretty").exists():
                fps.append(f'  (lib (name "{nick}")(type "KiCad")'
                           f'(uri "${{{LIB_VAR}}}/{nick}.pretty")'
                           f'(options "")(descr "{cat} footprints"))')
        (BUILD / "sym-lib-table").write_text(
            "(sym_lib_table\n  (version 7)\n" + "\n".join(syms) + "\n)\n")
        (BUILD / "fp-lib-table").write_text(
            "(fp_lib_table\n  (version 7)\n" + "\n".join(fps) + "\n)\n")

    # ---- report ----------------------------------------------------------
    print(f"{stats['sym']} symbols, {stats['fp']} footprints, "
          f"{stats['model']} 3D models -> {BUILD}")
    print(f"{stats['linked']} symbol->footprint links repaired\n")
    if warn:
        print(f"{len(warn)} item(s) need attention:")
        for w in warn:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
