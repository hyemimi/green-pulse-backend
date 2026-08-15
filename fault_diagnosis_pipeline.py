#!/usr/bin/env python3
"""Current-best chemical process early fault diagnosis pipeline.

This master runner orchestrates the exact experiment modules included in ./scripts.
It reproduces the current pipeline in four stages:
  1) F1/F3 thermal multi-CUSUM + A/B-specific classifier
  2) F2 feed Stage1/Stage2 features and event table
  3) Integrated F1/F3 + F2 + F4 specialists
  4) Thermal arbitration (recommended hold=0 is reported in the output grid)

Example:
    python final_fault_diagnosis_pipeline.py \
        --data /content/chemical_process_timeseries.csv \
        --workspace /content/fault_run

Dependencies: numpy, pandas, scikit-learn, numba, xgboost, matplotlib
"""
from pathlib import Path
import argparse, shutil, subprocess, sys, re, os

SCRIPT_DIR = Path(__file__).resolve().parent / "scripts"

STEPS = [
    ("thermal", "01_thermal_multicusum_normalml.py", "thermal_multicusum_normalml_outputs/test_candidate_events.csv"),
    ("f2", "02_f2_stage3_3feature_verifier.py", "f2_stage3_3feature_verifier/all_stage2_events_with_stage3_scores.csv"),
    ("integration", "04_integrated_specialists_v1.py", "integrated_specialists_v1_outputs/integrated_test_events.csv"),
    ("arbitration", "05_thermal_arbitration_v2.py", "integrated_arbitration_v2/arbitration_summary.csv"),
]

def patch_script(src: Path, dst: Path, workspace: Path):
    text = src.read_text(encoding="utf-8")
    # The experiment scripts were originally developed under /mnt/data.
    # Patch that root to a user-selected workspace without changing model logic.
    text = text.replace("/mnt/data", str(workspace))
    dst.write_text(text, encoding="utf-8")


def run_script(script: Path, log_path: Path):
    print(f"\n[RUN] {script.name}")
    with log_path.open("w", encoding="utf-8") as log:
        p = subprocess.run([sys.executable, str(script)], stdout=log, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-5000:]
        raise RuntimeError(f"{script.name} failed. Last log lines:\n{tail}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="chemical_process_timeseries.csv path")
    ap.add_argument("--workspace", default="./fault_run", help="output/work directory")
    ap.add_argument("--reuse-existing", action="store_true", help="skip a step when its marker output already exists")
    args = ap.parse_args()

    data = Path(args.data).resolve()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "logs").mkdir(exist_ok=True)
    (workspace / "_patched_scripts").mkdir(exist_ok=True)

    # Keep the canonical filename expected by the exact experiment modules.
    canonical = workspace / "chemical_process_timeseries(1).csv"
    if canonical.exists() or canonical.is_symlink():
        canonical.unlink()
    try:
        canonical.symlink_to(data)
    except OSError:
        shutil.copy2(data, canonical)

    for step_name, filename, marker_rel in STEPS:
        marker = workspace / marker_rel
        if args.reuse_existing and marker.exists():
            print(f"[SKIP] {step_name}: {marker}")
            continue

        # Integration expects the F2 event table under integration_work/...
        if step_name == "integration":
            src_dir = workspace / "f2_stage3_3feature_verifier"
            dst_dir = workspace / "integration_work" / "f2_stage3_3feature_verifier"
            dst_dir.mkdir(parents=True, exist_ok=True)
            needed = src_dir / "all_stage2_events_with_stage3_scores.csv"
            if not needed.exists():
                raise FileNotFoundError(f"F2 stage output missing: {needed}")
            shutil.copy2(needed, dst_dir / needed.name)

        src = SCRIPT_DIR / filename
        if not src.exists():
            raise FileNotFoundError(src)
        patched = workspace / "_patched_scripts" / filename
        patch_script(src, patched, workspace)
        run_script(patched, workspace / "logs" / f"{step_name}.log")

    final_summary = workspace / "integrated_arbitration_v2" / "arbitration_summary.csv"
    final_eps = workspace / "integrated_arbitration_v2" / "episode_results_hold0.csv"
    print("\n[DONE]")
    print("Final arbitration summary:", final_summary)
    print("Recommended hold=0 episode results:", final_eps)
    print("Logs:", workspace / "logs")

if __name__ == "__main__":
    main()
