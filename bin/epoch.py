#!/usr/bin/env python3
"""
Epoch preprocessed data into Face and Car trials using the events.tsv value column.
Faces = values 1-40, Cars = values 41-80.
"""

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

import mne
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

FACE_CODES = list(range(1, 41))
CAR_CODES = list(range(41, 81))


def main():
    parser = argparse.ArgumentParser(description="Epoch EEG data")
    parser.add_argument("--input", required=True, help="Preprocessed .fif file")
    parser.add_argument("--input-events", required=True, help="Events TSV")
    parser.add_argument("--output", required=True, help="Output epochs .fif")
    args = parser.parse_args()

    logger.info(f"Loading {args.input}")
    raw = mne.io.read_raw_fif(args.input, preload=True, verbose="WARNING")

    # Parse events.tsv
    events_df = pd.read_csv(args.input_events, sep="\t")
    # Keep only numeric values
    numeric_mask = events_df["value"].apply(lambda x: str(x).replace(".", "", 1).replace("-", "", 1).isdigit())
    events_df = events_df[numeric_mask].copy()
    events_df["value"] = events_df["value"].astype(float).astype(int)

    sfreq = raw.info["sfreq"]
    samples = (events_df["onset"].values * sfreq).astype(int)
    event_ids = events_df["value"].values.astype(int)
    events = np.column_stack([samples, np.zeros_like(samples), event_ids])

    # Keep only face/car events and recode to single integers
    valid_mask = np.isin(events[:, 2], FACE_CODES + CAR_CODES)
    events = events[valid_mask]
    events[:, 2] = np.where(np.isin(events[:, 2], FACE_CODES), 1, 2)
    event_id = {"face": 1, "car": 2}

    tmin, tmax = -0.2, 0.8
    baseline = (-0.2, 0.0)
    picks = mne.pick_types(raw.info, eeg=True, eog=True, exclude="bads")

    try:
        epochs = mne.Epochs(
            raw,
            events,
            event_id=event_id,
            tmin=tmin,
            tmax=tmax,
            baseline=baseline,
            picks=picks,
            preload=True,
            verbose="WARNING",
        )
    except Exception as e:
        logger.error(f"Epoching failed: {e}")
        sys.exit(1)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    epochs.save(args.output, overwrite=True)
    logger.info(f"Saved {len(epochs)} epochs to {args.output}")


if __name__ == "__main__":
    main()
