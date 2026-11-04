"""Box-guided SAM image-space comparison of the actual elbow probe, no actuation."""
import json
import os
from pathlib import Path

import meta_sam_parser as sam
import numpy as np

from premonition.cli import load_env_file
from premonition.meta import Budget,MetaClient
from premonition.scene_vision import load_capture,object_evidence

PROJECT=Path(__file__).resolve().parent.parent
TRIAL="f179da0131264572a59eab23080a3c14"


def main():
    root=PROJECT/"runs"
    folder=root/"real/calibration"
    path=folder/"step_vision"/(TRIAL+"_sam.json")
    if path.exists(): raise ValueError("Pair already recorded; do not repeat paid calls.")
    trial=json.loads((folder/"trials"/(TRIAL+".json")).read_text(encoding="utf-8"))
    load_env_file(PROJECT/".env")
    usage=[]
    client=MetaClient(os.environ["MODEL_API_KEY"],Budget(max_calls=2,max_usd=.01),on_usage=usage.append)
    frames=[]
    try:
        for phase in ("before","after"):
            jpeg,_,frame=load_capture(root,trial[phase+"_capture"])
            prompt=sam.build_object_prompt(size=(1920,1080),objects=[sam.PromptObject(id=0,prompts=[
                sam.FramePrompt(box=sam.PromptBox(350,100,810,400))])])
            records=client.segment(jpeg,prompt)
            if len(records)!=1: raise ValueError("Exactly one SAM mask is required for this comparison.")
            record=records[0]
            evidence=object_evidence(record,"gripper",1920,1080)
            mask=np.frombuffer(record.raster,np.uint8).reshape(record.mask_shape)>0
            ys,xs=np.nonzero(mask)
            if not len(xs): raise ValueError("Empty mask.")
            centroid=[float(xs.mean()+record.box[0]),float(ys.mean()+record.box[1])]
            frames.append({"phase":phase,"capture":frame,"seed_box_xyxy":[350,100,810,400],
                           "prompt_type":"selected_box","object":evidence,"centroid_xy_px":centroid})
    finally:
        client.http.close()
    delta=[round(frames[1]["centroid_xy_px"][i]-frames[0]["centroid_xy_px"][i],2) for i in (0,1)]
    report={"trial_id":TRIAL,"frames":frames,"centroid_delta_xy_px":delta,"api_usage":usage,
            "motion_validated":False,"note":"Image-space mask comparison with the same manually selected region. Mask consistency requires visual review; no world distance, smoothness or collision-free path inferred."}
    path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"trial_id":TRIAL,"centroids":[f["centroid_xy_px"] for f in frames],
                      "boxes":[f["object"]["box_xyxy"] for f in frames],"delta_xy_px":delta,"usage":usage},indent=2))


if __name__=="__main__":main()
