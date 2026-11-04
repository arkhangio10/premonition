"""Two-camera closed loop: hover the gripper tip over the sponge's top edge in both views, one capped step at a time."""
import base64, json, math, subprocess, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
from premonition.jetson import _script, read_commanded_pulses, ssh_argv
from premonition.scene_detect import locate_object as sponge
from premonition.visual_servo import BASE_PX, locate_tip
from inspection.approach_probe_20261102 import ENVELOPE

S, RUN, MAX_MOVES = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
STATEMENT = "es que tiene que ser retroalimentacion constante, usa las dos camaras, cierra lo que tengas que cerrar"
RECORD = Path("runs/real/calibration") / f"visual_loop_twocam_{RUN}.json"
JOINTS = ("wrist_pitch", "shoulder", "base", "elbow")
MAX_STEP, MIN_STEP = 60, 20
HOVER_PX, W1, W2 = 60, 0.6, 1.0
DONE_C922, DONE_USB = 40, 25


def capture_usb(path):
    r = subprocess.run(ssh_argv("jetson-usb", f"python3 - --token {uuid.uuid4().hex} --device 1 --reads 30"),
                       input=_script("capture_once.py"), capture_output=True, timeout=90)
    reply = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    if not reply.get("ok"):
        raise RuntimeError(f"USB capture failed: {reply.get('error')}")
    path.write_bytes(base64.b64decode(reply["jpeg_b64"]))
    return cv2.imread(str(path))


def observe(index):
    out = subprocess.run([sys.executable, "inspection/session_tools_20261102/photo.py", str(S)], capture_output=True, text=True, timeout=120)
    if out.returncode:
        raise RuntimeError("C922 photo failed: " + out.stderr[-300:])
    capture = json.loads((S / "current_capture.json").read_text(encoding="utf-8"))
    c922 = cv2.imread(str(Path("runs/real/captures") / capture["file"]))
    usb = capture_usb(S / f"twocam_{RUN}_{index:02d}_usb.jpg")
    obs = {"capture": capture["file"], "pulses": read_commanded_pulses("jetson-usb")["commanded_us"],
           "tip": [locate_tip(c922, BASE_PX["c922"]), locate_tip(usb, BASE_PX["usb"])],
           "sponge": [sponge(c922), sponge(usb)]}
    tiles = []
    for image, tip, sp in zip((c922, usb), obs["tip"], obs["sponge"]):
        vis = image.copy()
        if sp:
            cv2.circle(vis, (int(sp["cx"]), int(sp["top"] - HOVER_PX)), 18, (0, 255, 0), 4)
        if tip:
            cv2.circle(vis, (int(tip[0]), int(tip[1])), 18, (0, 255, 255), 4)
        tiles.append(cv2.resize(vis, (960, 540)))
    cv2.imwrite(str(S / "twocam_now.jpg"), np.hstack(tiles))
    return obs


def error(obs):
    (t1, t2), (s1, s2) = obs["tip"], obs["sponge"]
    e = [0.0, 0.0, s2["cx"] - t2[0], s2["top"] - HOVER_PX - t2[1]]
    if t1 is not None and s1 is not None:
        e[:2] = [s1["cx"] - t1[0], s1["top"] - HOVER_PX - t1[1]]
    return np.array(e)


def weights(obs):
    w1 = W1 if obs["tip"][0] is not None and obs["sponge"][0] is not None else 0.0
    return np.array([w1, w1, W2, W2])


def touches(tip2, sp2):
    return sp2["x0"] - 20 < tip2[0] < sp2["x1"] + 20 and tip2[1] > sp2["top"] - 15


def choose(record, obs):
    e, w = error(obs), weights(obs)
    pulses, sens = obs["pulses"], record["sensitivity"]
    best, best_cost = None, float(np.linalg.norm(w * e)) - 3
    for joint, j in sens.items():
        j = np.array(j)
        wj = w * j
        if not wj.any():
            continue
        wanted = float(wj @ (w * e) / (wj @ wj))
        sign = 1 if wanted > 0 else -1
        low, high = ENVELOPE[joint]
        room = high - 1 - pulses[joint] if sign > 0 else pulses[joint] - low - 1
        delta = sign * min(MAX_STEP, max(MIN_STEP, abs(round(wanted))), room)
        if abs(delta) < MIN_STEP:
            continue
        predicted = np.array(obs["tip"][1]) + j[2:] * delta
        if touches(predicted, obs["sponge"][1]):
            continue
        cost = float(np.linalg.norm(w * (e - j * delta)))
        if cost < best_cost:
            best, best_cost = (joint, delta, "model"), cost
    if best:
        return best
    for joint in JOINTS:
        if joint in sens:
            continue
        sign = {"wrist_pitch": 1, "shoulder": 1, "base": -1, "elbow": -1}[joint]
        if not ENVELOPE[joint][0] < pulses[joint] + sign * MAX_STEP < ENVELOPE[joint][1]:
            sign = -sign
        return joint, sign * MAX_STEP, "probe"
    return None


def main():
    record = (json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists()
              else {"run": RUN, "started_at": datetime.now(timezone.utc).isoformat(), "sensitivity": {}, "history": []})
    start = len(record["history"])
    for n in range(MAX_MOVES + 1):
        index = start + n
        obs = observe(index)
        entry = {"at": datetime.now(timezone.utc).isoformat(), **obs}
        record["history"].append(entry)
        if obs["tip"][1] is None or obs["sponge"][1] is None:
            entry["decision"] = "stop: tip or sponge not visible in the USB view"
        else:
            last = record["history"][-2] if len(record["history"]) > 1 else None
            if last and last.get("step") and last["tip"][1] is not None:
                joint, delta = last["step"]["joint"], last["step"]["applied_us"]
                if delta:
                    moved = -(error(obs) - error(last))
                    if last["tip"][0] is None or obs["tip"][0] is None:
                        moved[:2] = np.array(record["sensitivity"].get(joint, [0, 0, 0, 0]))[:2] * delta
                    measured = moved / delta
                    old = record["sensitivity"].get(joint)
                    record["sensitivity"][joint] = (measured if old is None else 0.5 * np.array(old) + 0.5 * measured).tolist()
            e = error(obs)
            entry["error"] = e.round(1).tolist()
            step = last and last.get("step")
            if step and step["joint"] == "elbow" and obs["pulses"]["elbow"] > 2000 and last["tip"][1] is not None                     and math.dist(obs["tip"][1], last["tip"][1]) < 5:
                entry["decision"] = "stop: elbow step beyond 2000 us did not move the tip (possible mechanical stop)"
            elif touches(obs["tip"][1], obs["sponge"][1]):
                entry["decision"] = "stop: tip at or below the sponge top in the USB view"
            elif abs(e[2]) <= DONE_USB and abs(e[3]) <= DONE_USB and (not weights(obs)[0] or math.hypot(*e[:2]) <= DONE_C922):
                entry["decision"] = "done: hovering over the sponge in both views"
            elif n == MAX_MOVES:
                entry["decision"] = "stop: move budget"
            else:
                pick = choose(record, obs)
                if pick is None:
                    entry["decision"] = "stop: no joint reduces the error inside the envelope"
                else:
                    joint, delta, why = pick
                    target = obs["pulses"][joint] + delta
                    name = f"twocam_{RUN}_{index:02d}"
                    r = subprocess.run([sys.executable, str(S / "step.py"), str(S), name, joint, str(target),
                                        f"Two-camera loop {RUN}: {why} step of {joint}.", "4", STATEMENT],
                                       capture_output=True, text=True, timeout=150)
                    after = read_commanded_pulses("jetson-usb")["commanded_us"]
                    entry["step"] = {"joint": joint, "target_us": target, "why": why, "rc": r.returncode,
                                     "applied_us": after[joint] - obs["pulses"][joint]}
                    entry["decision"] = f"move {joint} {delta:+d} ({why})"
                    if r.returncode:
                        entry["decision"] = "stop: step failed; do not resend"
                        entry["step"]["stderr"] = r.stderr[-400:]
        RECORD.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        tip = obs["tip"]
        print(index, entry["decision"], "| err", entry.get("error"), "| tip", [t and [round(v) for v in t] for t in tip],
              "| pulses", {k: obs["pulses"][k] for k in JOINTS}, flush=True)
        if not entry["decision"].startswith("move"):
            break
    print("sensitivity:", {k: [round(v, 2) for v in j] for k, j in record["sensitivity"].items()})


if __name__ == "__main__":
    main()
