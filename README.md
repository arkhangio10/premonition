# Premonition Lab

Low-cost robot arms sit in classrooms, maker spaces and small labs, but nobody trusts them with a real task. Hobby
servos drift, there are no encoders, and a bumped camera silently breaks any calibration. Premonition Lab lets such an
arm **map its own reach, refuse to move when its view has changed, and learn to grasp from its own failures**, with
Meta's models integrated for scene analysis, task planning and phase explanations.

The hardware is a 6-servo desk arm driven by a PCA9685 board on a Jetson Nano. It has no encoders, and its only
sensors are two webcams on the Jetson (a Logitech C922 in front and a USB camera at the side). Everything else runs on
a Windows PC.

## What it does

1. **Maps itself.** One command visits a grid of poses and records where both cameras see the blue gripper. The
   atlas has 102 poses. The latest repeatability check reports 0.50 px in front; the side view needs revalidation
   after a jump in the measured position (40.83 px, versus 0.34 px in the first pass). A closed-loop reach uses the atlas's local
   Jacobian with Broyden updates, so it needs no kinematic calibration.
2. **Checks its eyes before moving.** A printed ArUco tag on the table and image alignment tell whether a camera was
   bumped. The result is `still`, `rebase` (small drift, re-anchored) or `rescan`, and with `rescan` the arm will not
   move.
3. **Learns to grasp.** A policy samples among 20 grasp settings with Thompson sampling: offset, descent depth,
   steps, gripper opening and elbow limit. It labels every try as `lifted`, `pushed`, `too_shallow`, `slipped`,
   `closed_on_air`, `reach_failed` and so on, and the memory persists across runs
   (`runs/real/calibration/skill_memory.json`).
4. **Integrates Meta's models outside the fast control loop.** Muse Spark and SAM 3.1 have analyzed real calibration
   photos. The task code integrates Muse as planner and phase judge, with SAM as the object-finding fallback.
   The first physical lift used local checks only; a full physical Muse task is still pending. See [Meta models](#meta-models).
5. **Shows its work.** The bench page `/autonomy` has:
   - both live cameras and a 3D view of the fitted arm with its scanned reach;
   - the current phase, each try and Muse's verdicts;
   - what the policy has learned;
   - the last attempts with photos;
   - a replay of every recorded move.

## Results so far

Results are counted honestly, so one success is not reliability.

- **First autonomous grasp, 4 Nov 01:32 (Lima).** It came after 11 learning rounds and 35 grasp tries. The arm
  reached, descended, closed, lifted the sponge and released it, on its own. Between tries the operator re-seated
  the sponge.
  - Outcomes of the 35 tries: 12 `reach_failed`, 9 `pushed`, 6 `too_shallow`, 4 `not_lifted`, 1 `object_lost`,
    1 `closed_on_air`, 1 `slipped` and 1 `lifted`.
  - The release was logged as `not_released` by the rule in force at the time, which was fixed two minutes later.
    The photo shows the open gripper and the sponge back on the table.
  - Photos: `inspection/grasp-012956-try5-*.jpg` and `inspection/autonomy-place-20261103.jpg`.
  - The sponge was released at the pick-up location. A transfer to a different destination and a full task with
    Muse have not yet been demonstrated in the recorded evidence.
- **3D fit of the arm and both cameras:** approximate. Reprojection RMS is 6.3 px (C922) and 7.3 px (USB), above
  the 6 px target. The bench labels it «approximate geometry».
- **Tests:** 584 automated tests with fake hardware. None touches the arm, the cameras or the Meta API.

Day-by-day details, including what failed, are in [STATUS.md](STATUS.md) (Spanish).

## Run it without the robot

Requirements: Windows and Python 3.11.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m premonition serve
```

Open <http://127.0.0.1:8765>. The app listens on this machine only.

- **`/autonomy`, the bench.** It shows the recorded data from the real arm: what the policy learned, the last
  attempts with their photos, the scanned reach in 3D, and a **Replay** of every recorded session. Live cameras only
  appear while the arm is running.
- **`/`, a simulated kit-assembly demo.** It is the predict → act → verify loop on synthetic scenes (success, failed
  grasp, wrong piece, missing piece). Its images are marked `SYNTHETIC TEST DATA`.
- **`/calibration`, the teach page.** It shows the saved photos and the Muse + SAM scene analysis.

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Meta API key (optional)

Copy `.env.example` to `.env` and set `MODEL_API_KEY`; `.env` is git-ignored. Without a key, the simulated demo uses
fixtures, and the arm still works with local checks only. `PREMONITION_MAX_META_CALLS` and `PREMONITION_MAX_META_USD`
cap calls and estimated spend per process. To check access with one tiny call to each model, run
`python -m premonition meta-smoke`.

## Run it on the arm

The web app **never** moves the arm; motion only runs from the terminal. Every order goes through
`premonition/arm_session.py`, which enforces:

- strict per-joint pulse limits;
- at most 300 µs per order and 300 µs/s;
- at least 0.5 s per move;
- an SHA-256 check of the controller script on the Jetson.

The servo controller on the Jetson is not part of this repository. Each tool serves both cameras live at
<http://127.0.0.1:8767> before its first move.

| Step | Command (`.\.venv\Scripts\python.exe …`) |
| --- | --- |
| Scan the reach (sponge off the table, ~5 min) | `-m inspection.capability_scan_20261103` |
| Check that no camera moved | `-m inspection.arm_checks_20261103 views` (also `agree`, `scale`, `holdout`, `backlash`, `fit`) |
| Learn to grasp, then place | `inspection/session_tools_20261103/grasp_place.py --learn` |
| Full task with Muse | `inspection/autonomy_run_20261103.py --instruction "put the sponge next to the plate" [--dry-run]` |

While a tool runs, open `/autonomy` to watch it.

## Meta models

All are called through the Meta Model API with a per-process budget, and every call is logged with its latency and
cost.

| Model | Role |
| --- | --- |
| **Muse Spark** (`muse-spark-1.3`), planner | Reads both camera frames and the instruction and returns a JSON plan under a strict schema. The destination point can only choose a base angle inside a fixed safe range. |
| **Muse Spark**, judge | Implemented to compare before and after frames after each grasp or place phase and return success, a next move and a written reason. Local checks decide pass or fail. The first physical lift did not call Muse; a physical task with its verdicts is still pending. |
| **Muse Spark**, calibration analyst | `premonition analyze-arm` sends three real photos plus the servo pulses and gets a structured description with evidence and uncertainty. |
| **SAM 3.1** | Segments the sponge and gripper in real photos («Analyze scene», guided by a region from Muse when the name search fails). It is also the fallback object finder when color detection loses the sponge. |
| **Muse Image** (`muse-image-1.0`) | In the simulated demo, renders the expected result before each step. Verifier A3 (measurements + reference) is compared with A2 (measurements only). |

Muse is kept out of the fast control loop, because a call takes about 5 s. Every Muse output is bounded by code and
checked against a fresh photo.

## Layout

```text
premonition/   PC application: arm session, cameras, vision, reach, grasp policy, Muse/SAM client, web app
inspection/    bench tools that run the real arm (scan, checks, grasp-and-place, full task) and evidence photos
agent/         Jetson-side scripts (Python 3.6): camera capture, register reads
config/        simulated cell and taught reference poses
runs/real/     recorded bench data used by /autonomy (atlas, arm model, grasp memory, command log)
tests/         584 tests with fake transports
```

## Built during the hackathon

All code in this repository was written during the Meta Global AI Developer Hackathon (30 Oct – 4 Nov 2026).

## Limitations

- One object, an orange sponge, found by color with SAM as fallback. The destination is limited to a fixed base
  range.
- One lift in 35 tries is a first success, not a reliable skill. Distances are in pixels unless the table scale was
  measured.
- The PC side is Windows-only. The bench tools are tested on the bench, not in the unit tests.

## License

[MIT](LICENSE)
