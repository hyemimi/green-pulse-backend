"""Build the per-minute ESG energy-savings CSV consumed by NestJS.

The team must confirm the STY/F4 calculation policy before implementing
``calculate_energy_saved_kwh``. This script intentionally refuses to write
placeholder savings so demo values cannot be mistaken for measured results.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd


REQUIRED_INPUT_COLUMNS = {
    "timestamp",
    "reactor_id",
    "fault_type",
    "feed_flow_rate",
    "motor_current",
    "power_consumption_kw",
    "space_time_yield",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def default_physics_input() -> Path:
    """Find the physics-enhanced dataset without hard-coding a user directory."""

    configured_path = os.getenv("PHYSICS_DATASET_PATH")
    if configured_path:
        return Path(configured_path).expanduser()

    candidates = [
        PROJECT_ROOT / "chemical_process_timeseries_physics.csv",
        PROJECT_ROOT.parent
        / "green-pulse-backend-fault-detection-dev"
        / "chemical_process_timeseries_physics.csv",
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def calculate_energy_saved_kwh(fault_rows: pd.DataFrame) -> pd.Series:
    """Return estimated saved energy in kWh for each one-minute fault row.

    Implement the confirmed policy here:
    - F1/F2/F3: confirmed STY loss formula, integrated for one minute.
    - F4: confirmed excess motor-current formula, integrated for one minute.

    The function must return non-negative values with the same index as
    ``fault_rows``. Do not replace this error with zeros: zero is a real ESG
    result and would hide an unfinished calculation.
    """

    raise NotImplementedError(
        "The team has not confirmed the energy-savings formula yet. "
        "Implement calculate_energy_saved_kwh() before exporting the CSV."
    )


def build_output(source: pd.DataFrame, calculation_method: str, calculation_version: str) -> pd.DataFrame:
    missing = REQUIRED_INPUT_COLUMNS.difference(source.columns)
    if missing:
        raise ValueError(f"Missing input columns: {', '.join(sorted(missing))}")

    source = source.copy()
    source["timestamp"] = pd.to_datetime(source["timestamp"], errors="raise")
    fault_rows = source.loc[source["fault_type"].isin([1, 2, 3, 4])].copy()
    fault_rows["energy_saved_kwh"] = calculate_energy_saved_kwh(fault_rows)

    if fault_rows["energy_saved_kwh"].isna().any():
        raise ValueError("energy_saved_kwh contains missing values.")
    if (fault_rows["energy_saved_kwh"] < 0).any():
        raise ValueError("energy_saved_kwh must not contain negative values.")

    output = pd.DataFrame(
        {
            "timestamp": fault_rows["timestamp"],
            "reactor_id": fault_rows["reactor_id"],
            "fault_type": fault_rows["fault_type"].astype(int),
            "episode_id": fault_rows.get("episode_id"),
            "baseline_sty": fault_rows.get("baseline_sty"),
            "actual_sty": fault_rows.get("space_time_yield"),
            "baseline_power_kw": fault_rows.get("baseline_power_kw"),
            "actual_power_kw": fault_rows["power_consumption_kw"],
            "energy_saved_kwh": fault_rows["energy_saved_kwh"],
            "calculation_method": calculation_method,
            "calculation_version": calculation_version,
        }
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=default_physics_input(),
        type=Path,
        help="Physics-enhanced source CSV. Defaults to chemical_process_timeseries_physics.csv.",
    )
    parser.add_argument("--output", default=Path("fault_run/esg/energy_savings.csv"), type=Path)
    parser.add_argument("--method", default="sty-and-motor-current")
    parser.add_argument("--version", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = pd.read_csv(args.input)
    output = build_output(source, args.method, args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    print(f"saved rows={len(output)} path={args.output}")
    print(f"total energy_saved_kwh={output['energy_saved_kwh'].sum():.6f}")


if __name__ == "__main__":
    main()
