#!/bin/sh
# Every graded run of docs/data/geom_thin_prereg_20261021.md, sequential.
# usage: sh run_all.sh <out_dir>     (run at BelowNormal by the caller)
OUT="$1"
P="M:/claud_projects/bookscan/docs/data/geom_thin_20261021/thin_probe.py"
run() {  # name image L T R B
  echo "=== $1" >&2
  python "$P" "$2" "$3" "$4" "$5" "$6" "$OUT/lo_$1.json" "$OUT/side_$1.json" \
    > "$OUT/log_$1.txt" 2>&1 || echo "FAILED $1" >&2
}
for r in de_01 en_coins_01 en_coins_02 en_coins_03 it_geo_04 it_geo_05 it_geo_06 it_geo_07; do
  run "${r}_base" "$r" 0 0 0 0
done
run it_geo_06_ident it_geo_06 41 0 0 0
run it_geo_06_tiny  it_geo_06 4 0 0 0
run it_geo_06_R41   it_geo_06 0 0 41 0
run it_geo_06_T41   it_geo_06 0 41 0 0
run it_geo_06_B41   it_geo_06 0 0 0 41
run it_geo_07_ident it_geo_07 41 27 34 25
run it_geo_07_tiny  it_geo_07 4 0 0 0
run it_geo_07_L41   it_geo_07 41 0 0 0
run it_geo_07_R41   it_geo_07 0 0 41 0
run it_geo_07_T41   it_geo_07 0 41 0 0
run it_geo_07_B41   it_geo_07 0 0 0 41
run it_geo_07_mirror it_geo_07 34 25 41 27
echo DONE >&2
