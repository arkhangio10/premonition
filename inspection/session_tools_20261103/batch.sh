#!/bin/bash
# usage: batch.sh SCRATCH PREFIX JOINT DELTA COUNT ; each target is computed from the live readback; stops at the first failure
S="$1"; P="$2"; J="$3"; D="$4"; N="$5"
MSG="SI (llevar la esponja al frente de la mesa, bajar y abrir la pinza)"
for i in $(seq 1 "$N"); do
  .venv/Scripts/python.exe inspection/session_tools_20261102/photo.py "$S" > "$S/photo.log" 2>&1 || { cat "$S/photo.log"; exit 1; }
  CUR=$(.venv/Scripts/python.exe -c "import json,re,sys; t=open(sys.argv[1],encoding='utf-8').read(); print(json.loads(re.search(r'registers: (\{.*?\}\}) ', t).group(1))['commanded_us'][sys.argv[2]])" "$S/photo.log" "$J")
  T=$((CUR + D))
  OUT=$(.venv/Scripts/python.exe "$S/step.py" "$S" "${P}_$(printf %02d $i)" "$J" "$T" "Operator-directed motion, checked in both cameras after each step." 4 "$MSG" 2>&1)
  echo "$J $CUR -> $T | $(echo "$OUT" | grep -E "probe rc:")"
  echo "$OUT" | grep -q "probe rc: 0" || { echo "STOP"; echo "$OUT" | tail -4; exit 1; }
done
