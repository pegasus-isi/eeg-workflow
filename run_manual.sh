#!/bin/bash
#
# Manual test script for eeg-workflow.
# Downloads one subject, runs the full per-subject pipeline locally,
# then simulates a second subject to test the group contrast wrapper.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${SCRIPT_DIR}/test_data"
mkdir -p "${TEST_DIR}"
cd "${TEST_DIR}"

echo "=============================================="
echo "  EEG Workflow Manual Test"
echo "=============================================="
echo ""

# ---------------------------------------------------------------
# Step 1: Fetch one subject
# ---------------------------------------------------------------
echo "=== Step 1: Fetch subject 1001 ==="
python3 "${SCRIPT_DIR}/bin/fetch_subject.py" --subject-id 1001
ls -lh sub-1001_task-FacePerception_*

# ---------------------------------------------------------------
# Step 2: Preprocess
# ---------------------------------------------------------------
echo "=== Step 2: Preprocess ==="
python3 "${SCRIPT_DIR}/bin/preprocess.py" \
    --input-set sub-1001_task-FacePerception_eeg.set \
    --input-channels sub-1001_task-FacePerception_channels.tsv \
    --output preprocessed_1001_raw.fif

# ---------------------------------------------------------------
# Step 3: Epoch
# ---------------------------------------------------------------
echo "=== Step 3: Epoch ==="
python3 "${SCRIPT_DIR}/bin/epoch.py" \
    --input preprocessed_1001_raw.fif \
    --input-events sub-1001_task-FacePerception_events.tsv \
    --output epochs_1001_epo.fif

# ---------------------------------------------------------------
# Step 4: Average
# ---------------------------------------------------------------
echo "=== Step 4: Average ==="
python3 "${SCRIPT_DIR}/bin/average.py" \
    --input epochs_1001_epo.fif \
    --output-fif erp_1001.fif \
    --output-png erp_1001.png

# ---------------------------------------------------------------
# Step 5: Group contrast (simulate second subject)
# ---------------------------------------------------------------
echo "=== Step 5: Group contrast (simulated 2 subjects) ==="
cp erp_1001.fif erp_1002.fif
python3 "${SCRIPT_DIR}/bin/group_contrast.py" \
    --input erp_1001.fif \
    --input erp_1002.fif \
    --expected-ids "1001,1002" \
    --min-subjects 2 \
    --output-pdf n170_summary.pdf \
    --output-metrics metrics.json

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "=============================================="
echo "  MANUAL TEST COMPLETED SUCCESSFULLY"
echo "=============================================="
echo ""
ls -lh erp_1001.* n170_summary.pdf metrics.json
