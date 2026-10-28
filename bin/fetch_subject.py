#!/usr/bin/env python3
"""Download EEG data files for one subject from OpenNeuro S3."""

import argparse
import logging
import os
import sys

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://s3.amazonaws.com/openneuro.org/ds007096"


def main():
    parser = argparse.ArgumentParser(description="Fetch subject EEG data")
    parser.add_argument("--subject-id", required=True, help="Four-digit subject ID")
    args = parser.parse_args()

    sid = args.subject_id
    files = {
        f"sub-{sid}_task-FacePerception_eeg.set":
            f"{BASE_URL}/sub-{sid}/eeg/sub-{sid}_task-FacePerception_eeg.set",
        f"sub-{sid}_task-FacePerception_channels.tsv":
            f"{BASE_URL}/sub-{sid}/eeg/sub-{sid}_task-FacePerception_channels.tsv",
        f"sub-{sid}_task-FacePerception_events.tsv":
            f"{BASE_URL}/sub-{sid}/eeg/sub-{sid}_task-FacePerception_events.tsv",
    }

    for fname, url in files.items():
        logger.info(f"Downloading {fname} ...")
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            sys.exit(1)
        with open(fname, "wb") as f:
            f.write(r.content)
        logger.info(f"Saved {fname} ({os.path.getsize(fname)} bytes)")

    logger.info("Fetch complete.")


if __name__ == "__main__":
    main()
