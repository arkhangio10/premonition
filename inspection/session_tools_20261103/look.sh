#!/bin/bash
# usage: look.sh SCRATCH -> both cameras, sponge boxes, close-up pair in zoom.jpg (previous vs now)
S="$1"
cp "$S/bnow_c922.jpg" "$S/prev_c922.jpg"; cp "$S/bnow_usb.jpg" "$S/prev_usb.jpg"
.venv/Scripts/python.exe "$S/both_cams.py" "$S" bnow 2>&1 | grep registers | cut -c1-200
.venv/Scripts/python.exe - "$S" <<'PY'
import sys, importlib.util, cv2, numpy as np
from pathlib import Path
s = Path(sys.argv[1]); sys.argv = ["x", str(s), "look", "1"]
spec = importlib.util.spec_from_file_location("loop", s / "twocam_loop.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rows = []
for t in ("prev", "bnow"):
    tiles = []
    for cam, (y0, y1, x0, x1) in (("c922", (450, 1050, 150, 950)), ("usb", (200, 800, 300, 1100))):
        img = cv2.imread(str(s / f"{t}_{cam}.jpg")); sp = m.sponge(img)
        if t == "bnow": print(cam, "sponge", sp and {k: round(v) for k, v in sp.items()})
        tiles.append(img[y0:y1, x0:x1])
    rows.append(np.hstack(tiles))
cv2.imwrite(str(s / "zoom.jpg"), np.vstack(rows))
PY
