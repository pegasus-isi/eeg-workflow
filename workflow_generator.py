#!/usr/bin/env python3
"""
Pegasus workflow generator for EEG N170 analysis (OpenNeuro ds007096).

Pipeline (per-subject fan-out, then single fan-in):
  fetch_subject ──> preprocess ──> epoch ──> average
                                                  \
                                                   \
  group_contrast <───────────────────────────────────

Outputs per subject: erp_<ID>.fif, erp_<ID>.png
Group outputs: n170_summary.pdf, metrics.json
"""

import argparse
import logging
import os
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from Pegasus.api import *

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TOOL_CONFIGS = {
    "fetch_subject":   {"memory": "1 GB",  "cores": 1},
    "preprocess":      {"memory": "4 GB",  "cores": 2},
    "epoch":           {"memory": "4 GB",  "cores": 2},
    "average":         {"memory": "2 GB",  "cores": 1},
    "group_contrast":  {"memory": "4 GB",  "cores": 2},
}


class EEGWorkflow:
    wf = None
    sc = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    shared_scratch_dir = None
    local_storage_dir = None
    wf_name = "eeg_workflow"

    def __init__(self, dagfile="workflow.yml"):
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())
        self.shared_scratch_dir = os.path.join(self.wf_dir, "scratch")
        self.local_storage_dir = os.path.join(self.wf_dir, "output")

    def write(self):
        if self.sc is not None:
            self.sc.write()
        self.props.write()
        self.rc.write()
        self.tc.write()
        self.wf.write(file=self.dagfile)

    def create_pegasus_properties(self):
        self.props = Properties()
        self.props["pegasus.transfer.threads"] = "16"

    def create_sites_catalog(self, exec_site_name="condorpool"):
        self.sc = SiteCatalog()
        local = Site("local").add_directories(
            Directory(
                Directory.SHARED_SCRATCH, self.shared_scratch_dir
            ).add_file_servers(
                FileServer("file://" + self.shared_scratch_dir, Operation.ALL)
            ),
            Directory(
                Directory.LOCAL_STORAGE, self.local_storage_dir
            ).add_file_servers(
                FileServer("file://" + self.local_storage_dir, Operation.ALL)
            ),
        )
        exec_site = (
            Site(exec_site_name)
            .add_condor_profile(universe="vanilla")
            .add_pegasus_profile(style="condor")
        )
        self.sc.add_sites(local, exec_site)

    def create_transformation_catalog(self, exec_site_name="condorpool"):
        self.tc = TransformationCatalog()

        transformations = []
        for tool_name, config in TOOL_CONFIGS.items():
            tx = Transformation(
                tool_name,
                site=exec_site_name,
                pfn=os.path.join(self.wf_dir, f"bin/{tool_name}.py"),
                is_stageable=True,
            ).add_pegasus_profile(
                memory=config["memory"], cores=config.get("cores", 1)
            )
            transformations.append(tx)

        self.tc.add_transformations(*transformations)

    def create_replica_catalog(self):
        self.rc = ReplicaCatalog()
        pydeps_path = os.path.join(self.wf_dir, "pydeps.tar.gz")
        if os.path.exists(pydeps_path):
            self.rc.add_replica("local", "pydeps.tar.gz",
                                "file://" + os.path.abspath(pydeps_path))
        else:
            print(
                "WARNING: pydeps.tar.gz not found in %s. Jobs will run "
                "against the worker's system Python, which must already "
                "provide mne, pandas, and friends. Build the bundle first "
                "(see README.md, Setup step 1) for a self-contained run."
                % self.wf_dir,
                file=sys.stderr,
            )

    def create_workflow(self, args):
        self.wf = Workflow(self.wf_name, infer_dependencies=True)

        subject_ids = args.subject_ids[: args.num_subjects]
        pydeps_file = File("pydeps.tar.gz")
        has_pydeps = os.path.exists(os.path.join(self.wf_dir, "pydeps.tar.gz"))

        erp_files = []
        for sid in subject_ids:
            erp_fif = self._add_subject_pipeline(sid, pydeps_file, has_pydeps)
            erp_files.append(erp_fif)

        # Fan-in group contrast
        if erp_files:
            pdf_out = File("n170_summary.pdf")
            metrics_out = File("metrics.json")
            expected_ids_str = ",".join(subject_ids)

            group_job = (
                Job("group_contrast", _id="group_contrast", node_label="group_contrast")
                .add_args(
                    "--expected-ids", expected_ids_str,
                    "--min-subjects", str(args.min_subjects),
                    "--output-pdf", pdf_out,
                    "--output-metrics", metrics_out,
                )
                .add_inputs(*erp_files)
                .add_outputs(pdf_out, stage_out=True, register_replica=False)
                .add_outputs(metrics_out, stage_out=True, register_replica=False)
            )
            for erp in erp_files:
                group_job.add_args("--input", erp)
            if has_pydeps:
                group_job.add_inputs(pydeps_file)
            self.wf.add_jobs(group_job)

    def _add_subject_pipeline(self, sid, pydeps_file, has_pydeps):
        """Add per-subject jobs. Returns the erp .fif File object."""
        set_file      = File(f"sub-{sid}_task-FacePerception_eeg.set")
        channels_file = File(f"sub-{sid}_task-FacePerception_channels.tsv")
        events_file   = File(f"sub-{sid}_task-FacePerception_events.tsv")
        preproc_file  = File(f"preprocessed_{sid}_raw.fif")
        epochs_file   = File(f"epochs_{sid}_epo.fif")
        erp_fif       = File(f"erp_{sid}.fif")
        erp_png       = File(f"erp_{sid}.png")

        # 1. Fetch
        fetch_job = (
            Job("fetch_subject", _id=f"fetch_{sid}", node_label=f"fetch_{sid}")
            .add_args("--subject-id", sid)
            .add_outputs(set_file, channels_file, events_file,
                         stage_out=False, register_replica=False)
        )
        self.wf.add_jobs(fetch_job)

        # 2. Preprocess
        preproc_job = (
            Job("preprocess", _id=f"preprocess_{sid}", node_label=f"preprocess_{sid}")
            .add_args(
                "--input-set", set_file,
                "--input-channels", channels_file,
                "--output", preproc_file,
            )
            .add_inputs(set_file, channels_file)
            .add_outputs(preproc_file, stage_out=False, register_replica=False)
        )
        if has_pydeps:
            preproc_job.add_inputs(pydeps_file)
        self.wf.add_jobs(preproc_job)

        # 3. Epoch
        epoch_job = (
            Job("epoch", _id=f"epoch_{sid}", node_label=f"epoch_{sid}")
            .add_args(
                "--input", preproc_file,
                "--input-events", events_file,
                "--output", epochs_file,
            )
            .add_inputs(preproc_file, events_file)
            .add_outputs(epochs_file, stage_out=False, register_replica=False)
        )
        if has_pydeps:
            epoch_job.add_inputs(pydeps_file)
        self.wf.add_jobs(epoch_job)

        # 4. Average
        avg_job = (
            Job("average", _id=f"average_{sid}", node_label=f"average_{sid}")
            .add_args(
                "--input", epochs_file,
                "--output-fif", erp_fif,
                "--output-png", erp_png,
            )
            .add_inputs(epochs_file)
            .add_outputs(erp_fif, erp_png, stage_out=True, register_replica=False)
        )
        if has_pydeps:
            avg_job.add_inputs(pydeps_file)
        self.wf.add_jobs(avg_job)

        return erp_fif


def get_subject_ids():
    """Download participants.tsv and return ordered subject IDs (without 'sub-' prefix)."""
    url = "https://s3.amazonaws.com/openneuro.org/ds007096/participants.tsv"
    logger.info(f"Fetching participants list from {url}")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch participants.tsv: {e}")
        sys.exit(1)

    try:
        df = pd.read_csv(StringIO(resp.text), sep="\t")
    except Exception as e:
        logger.error(f"Failed to parse participants.tsv: {e}")
        sys.exit(1)

    if "participant_id" not in df.columns:
        logger.error("participants.tsv missing required 'participant_id' column")
        sys.exit(1)

    ids = (
        df["participant_id"]
        .dropna()
        .astype(str)
        .str.replace("sub-", "", regex=False)
        .tolist()
    )
    return ids


def main():
    parser = argparse.ArgumentParser(
        description="EEG N170 workflow generator for OpenNeuro ds007096",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --num-subjects 24 --output workflow.yml
  %(prog)s --subject-ids 1001 1002 1003 --num-subjects 3 --output workflow.yml
""",
    )
    parser.add_argument(
        "-s", "--skip-sites-catalog",
        action="store_true",
        help="Skip site catalog creation",
    )
    parser.add_argument(
        "-e", "--execution-site-name",
        metavar="STR", type=str, default="condorpool",
        help="Execution site name (default: condorpool)",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="STR", type=str, default="workflow.yml",
        help="Output workflow file (default: workflow.yml)",
    )
    parser.add_argument(
        "--num-subjects",
        type=int, default=24,
        help="Number of subjects to process (default: 24)",
    )
    parser.add_argument(
        "--subject-ids",
        type=str, nargs="+", default=None,
        help="Explicit subject IDs (overrides participants.tsv)",
    )
    parser.add_argument(
        "--min-subjects",
        type=int, default=None,
        help="Minimum subjects required for group stage (default: max(2, num_subjects))",
    )
    args = parser.parse_args()

    if args.num_subjects < 1:
        print("Error: --num-subjects must be >= 1", file=sys.stderr)
        sys.exit(1)

    if args.min_subjects is None:
        args.min_subjects = max(2, args.num_subjects)

    if args.min_subjects < 2:
        print("Error: --min-subjects must be >= 2", file=sys.stderr)
        sys.exit(1)

    if args.subject_ids is None:
        args.subject_ids = get_subject_ids()

    if args.num_subjects > len(args.subject_ids):
        logger.warning(
            f"Requested {args.num_subjects} subjects but only "
            f"{len(args.subject_ids)} available; using {len(args.subject_ids)}"
        )
        args.num_subjects = len(args.subject_ids)

    if args.min_subjects > args.num_subjects:
        logger.warning(
            f"--min-subjects ({args.min_subjects}) > available subjects "
            f"({args.num_subjects}); adjusting to {args.num_subjects}"
        )
        args.min_subjects = args.num_subjects

    logger.info("=" * 70)
    logger.info("EEG N170 WORKFLOW GENERATOR")
    logger.info("=" * 70)
    logger.info(f"Subjects to process: {args.num_subjects}")
    logger.info(f"Subject IDs: {args.subject_ids[:args.num_subjects]}")
    logger.info(f"Min subjects for group stage: {args.min_subjects}")
    logger.info(f"Execution site: {args.execution_site_name}")
    logger.info(f"Output file: {args.output}")
    logger.info("=" * 70)

    try:
        workflow = EEGWorkflow(dagfile=args.output)
        workflow.create_pegasus_properties()
        if not args.skip_sites_catalog:
            workflow.create_sites_catalog(exec_site_name=args.execution_site_name)
        workflow.create_transformation_catalog(exec_site_name=args.execution_site_name)
        workflow.create_replica_catalog()
        workflow.create_workflow(args)
        workflow.write()

        logger.info(f"\nWorkflow written to {args.output}")
        logger.info(
            f"Submit: pegasus-plan --submit "
            f"-s {args.execution_site_name} -o local {args.output}"
        )
    except Exception as e:
        logger.error(f"Failed to generate workflow: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
