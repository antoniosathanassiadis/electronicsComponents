./fix_components.sh #--apply
python3 build_kicad_libs.py --check
python3 load_list_of_components.py

export PATH="/Applications/KiCad/KiCad.app/Contents/MacOS:$PATH"
cd ~/Libs/electronicsComponents
python3 build_kicad_libs.py --upgrade