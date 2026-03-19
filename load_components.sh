#!/bin/bash

sym="*.kicad_sym"
sym_dir="symbol_collection"
rm -rf $sym_dir
mkdir -p $sym_dir
echo "loading symbols into $sym_dir/ ..."

shopt -s nullglob
for file in $sym */$sym */*/$sym */*/*/$sym */*/*/*/$sym; do
    echo "   $file"
    cp "$file" "$sym_dir/"
done

echo " "
foot="*.kicad_mod"
foot_dir="footprint_collection"
rm -rf $foot_dir
mkdir -p $foot_dir
echo "loading footprints into $foot_dir/ ..."

shopt -s nullglob
for file in $foot */$foot */*/$foot */*/*/$foot */*/*/*/$foot; do
    echo "   $file"
    cp "$file" "$foot_dir/"
done

echo " "
mod="*.step"
mod_dir="model_collection"
rm -rf $mod_dir
mkdir -p $mod_dir
echo "loading 3D models into $mod_dir/ ..."

shopt -s nullglob
for file in $mod */$mod */*/$mod */*/*/$mod */*/*/*/$mod; do
    echo "   $file"
    cp "$file" "$mod_dir/"
done

echo " "
n_sym=$(ls symbol_collection/ | wc -l)
n_foot=$(ls footprint_collection/ | wc -l)
n_mod=$(ls model_collection/ | wc -l)
echo "summary"
echo "   $n_sym symbols loaded"
echo "   $n_foot footprints loaded"
echo "   $n_mod 3D models loaded"

echo " "
echo "DONE"

