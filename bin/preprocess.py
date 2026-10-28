#!/usr/bin/env python3
"""
Preprocess continuous EEG:
- Load EEGLAB .set
- Map channels to standard_1020 montage using case-insensitive matching
- Re-reference to average
- Bandpass filter 0.1-40 Hz + notch 60 Hz
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
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Preprocess EEG data")
    parser.add_argument("--input-set", required=True, help="EEGLAB .set file")
    parser.add_argument("--input-channels", required=True, help="BIDS channels.tsv")
    parser.add_argument("--output", required=True, help="Output .fif file")
    args = parser.parse_args()

    logger.info(f"Input .set: {args.input_set}")
    logger.info(f"Input channels: {args.input_channels}")

    # Load EEGLAB file (pymatreader/h5py required in container)
    try:
        raw = mne.io.read_raw_eeglab(args.input_set, preload=True, verbose="WARNING")
    except Exception as e:
        logger.error(f"Failed to read EEGLAB file: {e}")
        sys.exit(1)

    # Read channels.tsv
    try:
        ch_df = pd.read_csv(args.input_channels, sep="\t")
        ch_names_tsv = ch_df["name"].astype(str).tolist()
    except Exception as e:
        logger.error(f"Failed to read channels.tsv: {e}")
        sys.exit(1)

    if set(raw.ch_names) != set(ch_names_tsv):
        logger.warning("Channel name mismatch between .set and channels.tsv; proceeding with .set names")

    # Apply standard_1020 montage matched case-insensitively
    montage = mne.channels.make_standard_montage("standard_1020")
    name_map = {}
    for ch in raw.ch_names:
        matches = [m for m in montage.ch_names if m.lower() == ch.lower()]
        if matches:
            name_map[ch] = matches[0]
        else:
            logger.warning(f"Channel {ch} not found in standard_1020 montage")
    if name_map:
        raw.rename_channels(name_map)

    raw.set_montage(montage, on_missing="ignore")
    raw.set_eeg_reference("average", projection=True)

    # Filter: bandpass 0.1-40 Hz, notch 60 Hz
    raw.filter(l_freq=0.1, h_freq=40.0, verbose="WARNING")
    raw.notch_filter(freqs=60.0, verbose="WARNING")

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    raw.save(args.output, overwrite=True)
    logger.info(f"Saved preprocessed data to {args.output}")


if __name__ == "__main__":
    main()
