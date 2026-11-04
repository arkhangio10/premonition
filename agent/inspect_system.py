#!/usr/bin/env python3
"""Inventario de solo lectura. No importa ni ejecuta programas del brazo (Python 3.6)."""
import ast
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import sys


def inspect():
    home = os.path.expanduser("~")
    programs = {}
    for name in ("mindarm_arm.py", "servo_test.py", "premonition_lab/premonition_agent.py"):
        path = os.path.join(home, name)
        if not os.path.isfile(path):
            programs[name] = {"installed": False}
            continue
        with open(path, "rb") as stream:
            raw = stream.read()
        tree = ast.parse(raw, filename=path)
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in (
                            "JOINTS", "LIMITS_US", "MAX_SPEED_US_S", "MAX_DURATION_S", "DISCONNECT_POLICY"):
                        try:
                            constants[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        programs[name] = {"installed": True, "path": path,
                          "sha256": hashlib.sha256(raw).hexdigest(), "constants": constants}
    processes = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/" + pid + "/cmdline", "rb") as stream:
                command = stream.read().replace(b"\x00", b" ").decode("utf-8", "replace")
            if any(term in command for term in ("mindarm_arm", "servo_test", "premonition_agent")):
                processes.append({"pid": int(pid), "command": command})
        except (IOError, OSError):
            pass
    return {
        "hostname": platform.node(), "platform": platform.platform(), "python": sys.version,
        "commands": {name: shutil.which(name) for name in (
            "python3", "python3.6", "python3.8", "pip3", "i2cdetect", "i2cget", "i2cset",
            "v4l2-ctl", "systemctl", "timeout", "servo_test", "mindarm_arm", "premonition")},
        "modules": {name: importlib.util.find_spec(name) is not None for name in ("cv2", "numpy", "smbus")},
        "video_devices": sorted(name for name in os.listdir("/dev") if name.startswith("video")),
        "programs": programs, "arm_processes": processes,
    }


if __name__ == "__main__":
    print(json.dumps(inspect()))
