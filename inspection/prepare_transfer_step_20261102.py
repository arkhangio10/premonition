"""Record the preceding image pair and prepare one reviewed step. Never actuates."""
import argparse
import json
import re
from datetime import datetime,timezone
from pathlib import Path

import httpx

from inspection.approach_probe_20261102 import build_review_command
from premonition.jetson import read_commanded_pulses
from premonition.scene_vision import load_capture
from premonition.teaching_hold import require_no_motion_hold


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--after-trial",required=True)
    p.add_argument("--name",required=True)
    p.add_argument("--joint",required=True)
    p.add_argument("--target",type=int,required=True)
    p.add_argument("--purpose",required=True)
    p.add_argument("--reviewed-capture-sha256",required=True)
    a=p.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}",a.after_trial) or not re.fullmatch(r"[a-z0-9_]+",a.name):
        raise ValueError("Invalid trial or review name.")
    root=Path(__file__).resolve().parent.parent/"runs"
    require_no_motion_hold(root)
    folder=root/"real/calibration"
    review_path=folder/("teaching_step_"+a.name+".json")
    if review_path.exists():raise ValueError("Never reset an existing one-use review.")
    s=httpx.get("http://127.0.0.1:8765/api/calibration").raise_for_status().json()
    before=read_commanded_pulses("jetson-usb")
    if before!=s["controller"]:raise ValueError("Refresh the controller check first.")
    _,_,frame=load_capture(root,s["capture"])
    if a.reviewed_capture_sha256!=frame["sha256"]:
        raise ValueError("The explicitly reviewed image differs from the current capture.")
    trial_path=folder/"trials"/(a.after_trial+".json")
    trial=json.loads(trial_path.read_text(encoding="utf-8"))
    if trial["after_readback"]!=before:raise ValueError("The previous trial does not match the current controller.")
    image_time=(root/"real/captures"/frame["file"]).stat().st_mtime
    trial_time=datetime.fromisoformat(trial["created_at"]).timestamp()
    if image_time<trial_time+trial["command"]["duration"]:
        raise ValueError("The image predates completion of the preceding command.")
    trial["after_capture"]=s["capture"]
    trial_path.write_text(json.dumps(trial,indent=2)+"\n",encoding="utf-8")
    if a.joint not in before["commanded_us"]:raise ValueError("Unknown joint.")
    review={"status":"prepared","prepared_at":datetime.now(timezone.utc).isoformat(),
            "base_fixed_operator_confirmed":True,"table_prepared_operator_confirmed":True,
            "authorization":"Ongoing operator-requested supervised teaching; base fixation, clear table, hands out and first base/elbow stability confirmed in chat.",
            "expected_readback":before,"purpose":a.purpose,
            "reviewed_capture_file":frame["file"],"reviewed_capture_sha256":a.reviewed_capture_sha256,
            "command":{"id":1,"cmd":"move","targets":dict(before["commanded_us"],**{a.joint:a.target}),"duration":4.0}}
    build_review_command(before,review)
    review_path.write_text(json.dumps(review,indent=2)+"\n",encoding="utf-8")
    session_path=folder/"transfer_session_20261102.json"
    session=json.loads(session_path.read_text(encoding="utf-8"))
    if a.after_trial not in session["trials"]:session["trials"].append(a.after_trial)
    session.update(updated_at=review["prepared_at"],status="teaching_elevated_alignment",current_controller=before,next_prepared_review=review_path.name,
                   first_base_elbow_operator_confirmed_stable=True)
    session_path.write_text(json.dumps(session,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"review":review_path.name,"command":review["command"]}))


if __name__=="__main__":main()
