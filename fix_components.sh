#!/usr/bin/env bash
#
# Repair the source tree that build_kicad_libs.py reports on.
#
#   ./fix_components.sh            dry run, prints every change it would make
#   ./fix_components.sh --apply    actually write
#
# Portable to macOS: works under bash 3.2, no `sed -i`, no bare `mktemp`,
# no GNU-only find predicates. Idempotent - running it twice is a no-op.
# Uses `git rm` for tracked files when inside a repo.
#
# WARNING: renaming a symbol breaks any existing schematic that already places
# it, because schematics store "LibNick:SymbolName". Run --apply before you
# start using these libraries in anger, not after.

set -euo pipefail

PREFIX="${PREFIX:-AA}"          # must match PREFIX in build_kicad_libs.py
ROOT="$(cd "$(dirname "$0")" && pwd)"
MODEL_VAR="\${${PREFIX}_3DMODELS}"
KICAD_VAR='${KICAD9_3DMODEL_DIR}'
TMPDIR_="${TMPDIR:-/tmp}"

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

cd "$ROOT"
IN_GIT=0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 && IN_GIT=1

if [ "$APPLY" = 1 ] && [ "$IN_GIT" = 1 ] && [ -n "$(git status --porcelain)" ]; then
    echo "!! working tree is dirty - commit or stash first" >&2
    exit 1
fi

COUNT_FILE="$(mktemp "$TMPDIR_/kicadfix.XXXXXX")"
trap 'rm -f "$COUNT_FILE"' EXIT
printf '0\n' > "$COUNT_FILE"

# note() survives subshells by counting through a file
note() {
    printf '  %s\n' "$1"
    printf '%s\n' "$(( $(cat "$COUNT_FILE") + 1 ))" > "$COUNT_FILE"
}
warn() { printf '  ?? %s\n' "$1" >&2; }

newtmp() { mktemp "$TMPDIR_/kicadfix.XXXXXX"; }

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

esc_re()  { printf '%s' "$1" | sed 's/[][\.*^$/]/\\&/g'; }   # -> sed BRE pattern
esc_rep() { printf '%s' "$1" | sed 's/[\/&]/\\&/g'; }        # -> sed replacement

# apply_sed <file> <sed args...>  write only if the result differs. 0 = changed.
apply_sed() {
    local f="$1"; shift
    local tmp; tmp="$(newtmp)"
    sed "$@" "$f" > "$tmp"
    if cmp -s "$f" "$tmp"; then rm -f "$tmp"; return 1; fi
    [ "$APPLY" = 1 ] && cat "$tmp" > "$f"
    rm -f "$tmp"
    return 0
}

remove() {
    local f="$1"
    [ -e "$f" ] || return 0
    note "rm  ${f#./}"
    [ "$APPLY" = 1 ] || return 0
    if [ "$IN_GIT" = 1 ] && git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        git rm -q --cached "$f" >/dev/null
    fi
    rm -f "$f"
    return 0
}

# rename_symbol <file> <old> <new> [new_value] [new_datasheet]
# Rewrites the top-level symbol name and its "<name>_u_v" unit sub-symbols.
rename_symbol() {
    local f="$1" old="$2" new="$3" val="${4:-}" ds="${5:-}"
    [ -f "$f" ] || { warn "missing $f"; return 0; }
    local o n
    o="$(esc_re "$old")"; n="$(esc_rep "$new")"
    # Match the symbol NAME only - "(symbol \"X\"" and its "X_u_v" unit
    # sub-symbols. A blanket replace would also hit Value/Description and
    # fight set_property below on every re-run.
    if grep -q "(symbol[[:space:]]*\"${o}\"" "$f" ||
       grep -q "(symbol[[:space:]]*\"${o}_" "$f"; then
        apply_sed "$f" \
            -e "s/\((symbol[[:space:]]*\)\"${o}\"/\1\"${n}\"/g" \
            -e "s/\((symbol[[:space:]]*\)\"${o}_/\1\"${n}_/g" \
            && note "sym ${f#./}: \"$old\" -> \"$new\"" || true
    fi
    [ -n "$val" ] && set_property "$f" Value "$val"
    [ -n "$ds" ]  && set_property "$f" Datasheet "$ds"
    return 0
}

# set_property <file> <property> <value>
# Updates the property if present; inserts it as the symbol's first child if not.
set_property() {
    local f="$1" p="$2" v="$3"
    [ -f "$f" ] || { warn "missing $f"; return 0; }
    if grep -q "property[[:space:]]*\"${p}\"" "$f"; then
        apply_sed "$f" \
            -e "s|\(([[:space:]]*property[[:space:]]*\"${p}\"[[:space:]]*\)\"[^\"]*\"|\1\"$(esc_rep "$v")\"|" \
            && note "set ${f#./}: $p = $v" || true
        return 0
    fi
    # not present: insert after the opening line of the first top-level symbol
    local tmp; tmp="$(newtmp)"
    awk -v prop="$p" -v val="$v" '
        BEGIN { done = 0 }
        { print }
        !done && /^[ \t]*\(symbol[ \t]+"/ {
            printf "    (property \"%s\" \"%s\" (at 0 0 0)\n", prop, val
            printf "      (effects (font (size 1.27 1.27)) hide)\n    )\n"
            done = 1
        }
    ' "$f" > "$tmp"
    if ! cmp -s "$f" "$tmp"; then
        [ "$APPLY" = 1 ] && cat "$tmp" > "$f"
        note "add ${f#./}: $p = $v"
    fi
    rm -f "$tmp"
    return 0
}

# --------------------------------------------------------------------------
# 0. line endings
# --------------------------------------------------------------------------
echo "== line endings =="
# The SamacSys/Ultra Librarian exports are CRLF. Mixed endings inside one
# merged library make every future diff useless.
while IFS= read -r f; do
    printf '\r' | cmp -s - /dev/null && true
    if grep -q "$(printf '\r')" "$f" 2>/dev/null; then
        apply_sed "$f" -e "s/$(printf '\r')\$//" && note "crlf ${f#./}" || true
    fi
done < <(find . -path ./.git -prune -o \
            \( -name '*.kicad_sym' -o -name '*.kicad_mod' \) -print |
         grep -v '/0collection')

# --------------------------------------------------------------------------
# 1. symbol names
# --------------------------------------------------------------------------
echo "== symbol names =="
# Vendor exports name the symbol after the order code, which is unreadable in
# a schematic and does not match the folder. Align each symbol with its file
# name and keep the MPN in Description so the chooser still finds it.
#
# file | old symbol name | new name | Value | Description
RENAMES="
active/analog/74HC123D/74HC123D.kicad_sym|74HC123D,653|74HC123D|74HC123D|Nexperia 74HC123D,653 dual retriggerable monostable multivibrator
active/analog/74HCT14DR/74HCT14DR.kicad_sym|SN74HCT14DR|74HCT14DR|74HCT14DR|TI SN74HCT14DR hex Schmitt-trigger inverter
active/analog/LM393/LM393.kicad_sym|LM393P|LM393|LM393|TI LM393P dual differential comparator
active/analog/TL071H/TL071H.kicad_sym|TL071HIDR|TL071H|TL071H|TI TL071HIDR JFET-input operational amplifier
active/digital/MCP4822/MCP4822.kicad_sym|MCP4822-E_SN|MCP4822|MCP4822|Microchip MCP4822-E/SN dual 12-bit DAC
connectors/Amphenol_USB-C/Amphenol_USB-C.kicad_sym|12402012E212A|Amphenol_USB-C|USB-C|Amphenol 12402012E212A USB-C receptacle
connectors/LEMO_00_Socket/LEMO_00_Socket.kicad_sym|EPK.00.250.NTN|LEMO_00_Socket|LEMO_00|LEMO EPK.00.250.NTN 00-series coaxial socket
connectors/SMA_F_Angled/SMA_F_Angled.kicad_sym|SMA-J-P-X-RA-TH1|SMA_F_Angled|SMA_F|Samtec SMA-J-P-X-RA-TH1 right-angle SMA jack
devices/RaspberryPi_4B/RaspberryPi_4B.kicad_sym|RASPBERRY_PI_4B_4GB|RaspberryPi_4B|RaspberryPi_4B|Raspberry Pi 4 Model B 4 GB
mechanics/PTS815/PTS815.kicad_sym|PTS815_SJM_250_SMTR_LFS|PTS815|PTS815|C&K PTS815 SJM 250 SMTR LFS tactile switch
passive/BFR92P/BFR92P.kicad_sym|BFR92PE6327HTSA1|BFR92P|BFR92P|Infineon BFR92PE6327HTSA1 NPN RF transistor
passive/MCP1700-3302/MCP1700-3302.kicad_sym|MCP1700T-3302E_TT|MCP1700-3302|MCP1700-3302|Microchip MCP1700T-3302E/TT 3.3 V LDO regulator
passive/UA78L05AC/UA78L05AC.kicad_sym|UA78L05ACD|UA78L05AC|UA78L05AC|TI UA78L05ACD 5 V linear regulator
photoelectronics/LED_Blue_Lumileds_L1C1-RYL/LED_UV_L1C1-RYL.kicad_sym|L1C1-RYL1000000000|LED_UV_L1C1-RYL|LED_UV|Lumileds L1C1-RYL1000000000 UV LED
photoelectronics/SiPM_Broadcom_AFBR-S4N22P014M/SiPM_Broadcom_AFBR-S4N22P014M.kicad_sym|AFBR-S4N22P014M|SiPM_Broadcom_AFBR-S4N22P014M|AFBR-S4N22P014M|Broadcom AFBR-S4N22P014M SiPM
photoelectronics/SiPM_Hamamatsu_S13360/SiPM_Hamamatsu_S13360-1325PE.kicad_sym|S13360-1325PE|SiPM_Hamamatsu_S13360-1325PE|S13360-1325PE|Hamamatsu S13360-1325PE MPPC
connectors/Pin_1.27mm/Pin_Header_02x05_P1.27mm.kicad_sym|62131021021|Pin_Header_02x05_P1.27mm|Conn_02x05_1.27mm|Wuerth 62131021021 2x5 pin header, 1.27 mm pitch
connectors/Pin_1.27mm/Pin_Socket_02x05_P1.27mm.kicad_sym|62201021821|Pin_Socket_02x05_P1.27mm|Conn_02x05_1.27mm|Wuerth 62201021821 2x5 pin socket, 1.27 mm pitch
passive/ESD9B5-0ST5G/ESD9B5-0ST5G.kicad_sym|ESD9B5.0ST5G|ESD9B5-0ST5G|ESD9B5-0ST5G|onsemi ESD9B5.0ST5G ESD protection diode
"
# STM32G473CBT6 is left alone on purpose: the MPN reads better in a schematic
# than the file name STM32G4-73CBT6-LQFP48 does.

printf '%s\n' "$RENAMES" | while IFS='|' read -r f old new val descr; do
    [ -n "${f:-}" ] || continue
    rename_symbol "$f" "$old" "$new" "$val"
    [ -n "${descr:-}" ] && set_property "$f" Description "$descr"
done

# LMC555.kicad_sym is byte-identical to LM555.kicad_sym: the CMOS part was
# never actually drawn. Both 555s share a pinout so the graphics are fine -
# only the identity is wrong. VERIFY this really is the part you stock.
rename_symbol active/analog/LMC555/LMC555.kicad_sym \
    LM555CN_NOPB LMC555 "LMC555" "https://www.ti.com/lit/gpn/lmc555"
set_property active/analog/LMC555/LMC555.kicad_sym Description \
    "TI LMC555 CMOS timer - graphics inherited from LM555, verify before use"

rename_symbol active/analog/LM555/LM555.kicad_sym \
    LM555CN_NOPB LM555 "LM555"
set_property active/analog/LM555/LM555.kicad_sym Description \
    "TI LM555CN/NOPB bipolar timer"

set_property passive/ESD9B5-0ST5G/ESD9B5-0ST5G.kicad_sym Datasheet \
    "https://www.onsemi.com/pdf/datasheet/ESD9B5.0ST5G-D.PDF"

# --------------------------------------------------------------------------
# 2. 3D model references
# --------------------------------------------------------------------------
echo "== 3D model references =="

# The vendored Pico footprints reach sideways into KiCad's own 3dshapes
# directory with a relative path. Anchor them to the stock model tree. This
# runs FIRST so the generic rule below sees valid ${KICAD...} refs and skips.
for fp in active/microcontroller/RaspberryPi_Pico/*.kicad_mod; do
    [ -e "$fp" ] || continue
    apply_sed "$fp" \
        -e "s|\"\\.\\./Module_RaspberryPi_Pico\\.3dshapes/|\"${KICAD_VAR}/Module_RaspberryPi_Pico.3dshapes/|g" \
        && note "3d  ${fp#./} -> stock Module_RaspberryPi_Pico.3dshapes" || true
done

# The .step files were already renamed to match their footprint; only the
# (model ...) line still carries the vendor filename. Point it at the sibling.
while IFS= read -r fp; do
    dir="$(dirname "$fp")"; stem="$(basename "$fp" .kicad_mod)"
    model=""
    for ext in step stp wrl igs; do
        [ -f "$dir/$stem.$ext" ] && { model="$stem.$ext"; break; }
    done
    [ -n "$model" ] || continue
    n_model="$(grep -c '(model' "$fp" || true)"
    [ "$n_model" -eq 0 ] && continue                    # absent: build script inserts it
    # Already-good references first, so a correctly anchored multi-model
    # footprint (the Pico ones above) does not raise a spurious warning.
    grep -q '(model[ \t]*"\${KICAD' "$fp" && continue  # valid stock reference
    grep -q "$(esc_re "$MODEL_VAR/$model")" "$fp" && continue   # already done
    if [ "$n_model" -gt 1 ]; then
        # Several distinct models in one footprint: collapsing them all onto
        # the single sibling file would silently duplicate it N times.
        warn "${fp#./}: $n_model model references, fix by hand"
        continue
    fi
    apply_sed "$fp" \
        -e "s|\((model[[:space:]]*\)\"[^\"]*\"|\1\"$(esc_rep "$MODEL_VAR/$model")\"|g" \
        && note "3d  ${fp#./} -> $MODEL_VAR/$model" || true
done < <(find . -path ./.git -prune -o -name '*.kicad_mod' -print |
         grep -v '/0collection')

# --------------------------------------------------------------------------
# 3. default footprint for genuinely multi-variant parts
# --------------------------------------------------------------------------
echo "== default footprints =="
# build_kicad_libs.py refuses to guess when a folder holds several footprints.
# Choose the default here; it stays changeable per placement in the schematic.
set_property active/analog/LM555/LM555.kicad_sym         Footprint "${PREFIX}_active:LM555_THT"
set_property active/analog/LMC555/LMC555.kicad_sym       Footprint "${PREFIX}_active:LMC555_THT"
set_property passive/ESD9B5-0ST5G/ESD9B5-0ST5G.kicad_sym Footprint "${PREFIX}_passive:ESD9B5-0ST5G"
# passive/R is deliberately left blank: a generic resistor should be assigned
# per placement. Uncomment to default it to 0603 instead.
# set_property passive/R/R.kicad_sym Footprint "${PREFIX}_passive:R_0603"

# --------------------------------------------------------------------------
# 4. symbols that duplicate libraries shipped with KiCad
# --------------------------------------------------------------------------
echo "== vendored stock symbols =="
# The footprints in these folders are your own short-named variants: keep them.
remove passive/C/C.kicad_sym
remove passive/LED/LED.kicad_sym
remove active/microcontroller/RaspberryPi_Pico/RaspberryPi_Pico.kicad_sym

# --------------------------------------------------------------------------
# 5. cruft
# --------------------------------------------------------------------------
echo "== cruft =="
# NOTE the -not -name '*.kicad_mod': the glob '*.mod' matches '*.kicad_mod'
# as well, and deleting every footprint in the repo would be a bad afternoon.
while IFS= read -r f; do remove "$f"; done < <(
    find . -path ./.git -prune -o \
        \( -name '*.lib' -o -name '*.dcm' -o -name '*.bak' -o -name '.DS_Store' \
           -o \( -name '*.mod' -not -name '*.kicad_mod' \) \) -print)

# --------------------------------------------------------------------------
# 6. .gitignore
# --------------------------------------------------------------------------
echo "== .gitignore =="
for pat in '.DS_Store' '*.bak' 'build/' \
           '0collection_symbols/' '0collection_footprints/' '0collection_models/'; do
    if ! grep -qxF "$pat" .gitignore 2>/dev/null; then
        note "gitignore += $pat"
        [ "$APPLY" = 1 ] && printf '%s\n' "$pat" >> .gitignore
    fi
done

# --------------------------------------------------------------------------
echo
CHANGED="$(cat "$COUNT_FILE")"
if [ "$APPLY" = 1 ]; then
    echo "$CHANGED change(s) applied."
    echo "Next: python3 build_kicad_libs.py --check"
else
    echo "$CHANGED change(s) pending. Re-run with --apply to write them."
fi