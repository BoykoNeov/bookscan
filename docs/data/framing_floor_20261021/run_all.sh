#!/bin/sh
# Every graded run of docs/data/framing_floor_prereg_20261021.md, sequential.
# usage: sh run_all.sh <out_dir>     (run at BelowNormal by the caller)
OUT="$1"
P="M:/claud_projects/bookscan/docs/data/framing_floor_20261021/floor_probe.py"
run() {  # name image L T R B [--rect]
  echo "=== $1 $(date +%H:%M:%S)" >&2
  python "$P" "$2" "$3" "$4" "$5" "$6" "$OUT/lo_$1.json" $7 \
    > "$OUT/log_$1.txt" 2>&1 || echo "FAILED $1" >&2
}
four() {  # rows with background on all four sides
  r="$1"
  run "${r}__base"   "$r" 0 0 0 0
  run "${r}__repeat" "$r" 0 0 0 0
  run "${r}__L4"  "$r" 4 0 0 0;  run "${r}__T4"  "$r" 0 4 0 0
  run "${r}__R4"  "$r" 0 0 4 0;  run "${r}__B4"  "$r" 0 0 0 4
  run "${r}__L41" "$r" 41 0 0 0; run "${r}__T41" "$r" 0 41 0 0
  run "${r}__R41" "$r" 0 0 41 0; run "${r}__B41" "$r" 0 0 0 41
  run "${r}__all25" "$r" 25 25 25 25
  run "${r}__all41" "$r" 41 41 41 41
}
two() {  # top and bottom only
  r="$1"
  run "${r}__base"   "$r" 0 0 0 0
  run "${r}__repeat" "$r" 0 0 0 0
  run "${r}__T4"  "$r" 0 4 0 0;  run "${r}__B4"  "$r" 0 0 0 4
  run "${r}__T41" "$r" 0 41 0 0; run "${r}__B41" "$r" 0 0 0 41
  run "${r}__all25" "$r" 0 25 0 25
  run "${r}__all41" "$r" 0 41 0 41
}
one() {  # bottom only
  r="$1"
  run "${r}__base"   "$r" 0 0 0 0
  run "${r}__repeat" "$r" 0 0 0 0
  run "${r}__B4"  "$r" 0 0 0 4
  run "${r}__all25" "$r" 0 0 0 25
  run "${r}__B41" "$r" 0 0 0 41
}
run it_geo_07__rect0 it_geo_07 0 0 0 0 --rect
four it_geo_07; four it_geo_06; four it_geo_05; four de_01
two en_coins_01; two en_coins_02
one en_coins_03; one it_geo_04
echo DONE >&2
