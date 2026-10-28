#!/usr/bin/env python3
"""Average epochs to evoked responses (faces, cars) and save .fif + .png."""

import argparse
import logging
import os
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
    parser = argparse.ArgumentParser(description="Average epochs to ERPs")
    parser.add_argument("--input", required=True, help="Epochs .fif file")
    parser.add_argument("--output-fif", required=True, help="Output evoked .fif")
    parser.add_argument("--output-png", required=True, help="Output plot PNG")
    args = parser.parse_args()

    epochs = mne.read_epochs(args.input, verbose="WARNING")

    try:
        evoked_face = epochs["face"].average()
        evoked_car = epochs["car"].average()
    except Exception as e:
        logger.error(f"Failed to compute evoked responses: {e}")
        sys.exit(1)

    # Save evokeds
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mne.write_evokeds(args.output_fif, [evoked_face, evoked_car])
    logger.info(f"Saved evokeds to {args.output_fif}")

    # Plot mean over N170 channels
    times_ms = evoked_face.times * 1000.0
    picks = mne.pick_channels(evoked_face.ch_names, N170_CHANNELS, ordered=False)
    if len(picks) == 0:
        logger.warning(f"N170 channels {N170_CHANNELS} not found; using all EEG")
        picks = mne.pick_types(evoked_face.info, eeg=True, exclude="bads")

    face_mean = evoked_face.data[picks].mean(axis=0) * 1e6
    car_mean = evoked_car.data[picks].mean(axis=0) * 1e6

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(times_ms, face_mean, label="Faces")
    ax.plot(times_ms, car_mean, label="Cars")
    ax.axhline(0, color="gray", linewidth=0.5)
    ax.axvline(0, color="gray", linewidth=0.5)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Amplitude (µV)")
    ax.set_title(f"Subject ERP")
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.output_png, dpi=150)
    plt.close(fig)
    logger.info(f"Saved plot to {args.output_png}")


if __name__ == "__main__":
    main()
