#!/bin/sh
# Regenerates the four masters (sources/) and OTFs (fonts/) from upstream Karrik.
#   git clone https://gitlab.com/phantomfoundry/karrik_fonts
#   pip install ufoLib2 fonttools pyclipper fontmake
set -e
SRC=${1:-karrik_fonts/sources}
C="Based on Karrik by Jean-Baptiste Morizot and Lucas Le Bihan (https://gitlab.com/phantomfoundry/karrik_fonts)."
gen() {
    src=$1 dst=$2; shift 2
    python offset_weight.py "$SRC/Karrik-$src.ufo" "sources/Karrik-$dst.ufo" \
        --zones -190 0 500 680 --keep-sidebearings --steps 16 --copyright "$C" "$@"
    fontmake -u "sources/Karrik-$dst.ufo" -o otf --output-dir fonts
}
gen Regular Bold        --delta 20 --delta-y 6 --style-name "Bold"         --weight-class 700 --glyph-delta germandbls=14
gen Italic  BoldItalic  --delta 20 --delta-y 6 --style-name "Bold Italic"  --weight-class 700 --glyph-delta germandbls=10
gen Regular Light       --delta -20            --style-name "Light"        --weight-class 300 --glyph-delta estimated=0
gen Italic  LightItalic --delta -20            --style-name "Light Italic" --weight-class 300 --glyph-delta estimated=0
