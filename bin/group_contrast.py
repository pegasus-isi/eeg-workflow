#!/usr/bin/env python3
"""
Group-level N170 contrast.

Loads per-subject evoked .fif files, computes grand averages,
difference wave (Face - Car), finds peak latency/amplitude of the
difference in the 150-200 ms window over occipitotemporal channels,
and writes a summary PDF + metrics JSON.

Exits non-zero if fewer than --min-subjects inputs are present,
naming the missing subjects.
"""

import argparse
import json
import logging
import os
import re
import sys
import tarfile

# Extract portable Python dependencies if staged by Pegasus
if os.path.exists("pydeps.tar.gz") and not os.path.exists("pydeps"):
    tarfile.open("pydeps.tar.gz", "r:gz").extractall("pydeps")
if os.path.exists("pydeps"):
    sys.path.insert(0, os.path.abspath("pydeps"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mne
import numpy as np
import warnings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

N170_CHANNELS = ["P8", "PO8", "O2"]


def main():
    parser = argparse.ArgumentParser(description="Group N170 contrast")
    parser.add_argument(
        "--input", action="append", required=True,
        help="Per-subject ERP .fif file (repeatable)",
    )
    parser.add_argument(
        "--expected-ids", required=True,
        help="Comma-separated expected subject IDs",
    )
    parser.add_argument(
        "--min-subjects", type=int, required=True,
        help="Minimum subjects required",
    )
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--output-metrics", required=True)
    args = parser.parse_args()

    expected_ids = [s.strip() for s in args.expected_ids.split(",")]
    actual_files = args.input
    actual_ids = []
    for f in actual_files:
        m = re.search(r"erp_(\d+)\.fif$", os.path.basename(f))
        if m:
            actual_ids.append(m.group(1))
        else:
            logger.warning(f"Could not parse subject ID from {f}")

    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    if len(actual_files) < args.min_subjects:
        logger.error(
            f"Only {len(actual_files)} subjects available, "
            f"but minimum required is {args.min_subjects}."
        )
        if missing_ids:
            logger.error(f"Missing subjects: {', '.join(missing_ids)}")
        sys.exit(1)

    logger.info(f"Including {len(actual_files)} subjects in group analysis")

    face_list = []
    car_list = []
    diff_list = []

    for fif in actual_files:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            evokeds = mne.read_evokeds(fif, verbose="WARNING")
        ev_face = [e for e in evokeds if e.comment == "face"][0]
        ev_car = [e for e in evokeds if e.comment == "car"][0]
        face_list.append(ev_face)
        car_list.append(ev_car)
        diff_list.append(mne.combine_evoked([ev_face, ev_car], weights=[1, -1]))

    # Grand averages
    grand_face = mne.grand_average(face_list)
    grand_car = mne.grand_average(car_list)
    grand_diff = mne.grand_average(diff_list)

    # Peak detection on difference wave (negative peak = N170)
    diff_pick = grand_diff.copy().pick(N170_CHANNELS)
    peak_result = diff_pick.get_peak(
        ch_type="eeg", tmin=0.15, tmax=0.20, mode="neg", return_amplitude=True
    )
    ch_name, latency, amplitude = peak_result
    latency = float(latency)
    amplitude = float(amplitude)
    amplitude_uv = amplitude * 1e6

    metrics = {
        "peak_latency_ms": round(latency * 1000, 2),
        "peak_amplitude_uv": round(amplitude_uv, 3),
        "num_subjects": len(actual_files),
        "n170_channels": N170_CHANNELS,
        "peak_channel": ch_name,
    }

    with open(args.output_metrics, "w") as f:
        json.dump(metrics, f, indent=2)
    logger.info(f"Metrics: {metrics}")

    # Plot
    times_ms = grand_face.times * 1000.0
    picks = mne.pick_channels(grand_face.ch_names, N170_CHANNELS, ordered=False)
    if len(picks) == 0:
        picks = mne.pick_types(grand_face.info, eeg=True, exclude="bads")

    face_mean = grand_face.data[picks].mean(axis=0) * 1e6
    car_mean = grand_car.data[picks].mean(axis=0) * 1e6
    diff_mean = grand_diff.data[picks].mean(axis=0) * 1e6

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].plot(times_ms, face_mean, label="Faces")
    axes[0].plot(times_ms, car_mean, label="Cars")
    axes[0].axhline(0, color="gray", linewidth=0.5)
    axes[0].axvline(0, color="gray", linewidth=0.5)
    axes[0].axvline(latency * 1000, color="k", linestyle="--", label=f"N170 peak")
    axes[0].set_xlabel("Time (ms)")
    axes[0].set_ylabel("Amplitude (µV)")
    axes[0].set_title("Grand Average ERPs")
    axes[0].legend()

    axes[1].plot(times_ms, diff_mean, color="purple", label="Face - Car")
    axes[1].axhline(0, color="gray", linewidth=0.5)
    axes[1].axvline(0, color="gray", linewidth=0.5)
    axes[1].axvline(
        latency * 1000, color="r", linestyle="--",
        label=f"Peak {latency*1000:.0f} ms, {amplitude_uv:.1f} µV",
    )
    axes[1].set_xlabel("Time (ms)")
    axes[1].set_ylabel("Amplitude (µV)")
    axes[1].set_title("N170 Difference Wave")
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(args.output_pdf, dpi=150)
    plt.close(fig)
    logger.info(f"Saved summary to {args.output_pdf}")


if __name__ == "__main__":
    main()
