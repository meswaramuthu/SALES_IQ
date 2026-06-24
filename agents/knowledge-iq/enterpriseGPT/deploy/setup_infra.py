#!/usr/bin/env python3
"""
Knowledge IQ — Infrastructure + RAG setup (Phases 1-3 only).

Runs:
  Phase 1 — Enable GCP APIs + create GCS bucket
  Phase 2 — Create or reuse RAG corpus
  Phase 3 — Upload tools_config.json and prompt.txt to GCS

Outputs the RAG corpus resource name at the end so it can be passed
to the agent deployment step.

Usage:
  python deploy/setup_infra.py --project my-project --bucket my-bucket

  # Reuse existing corpus
  python deploy/setup_infra.py --project my-project --bucket my-bucket \
      --corpus projects/123/locations/us-west1/ragCorpora/456
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR   = Path(__file__).parent.resolve()   # deploy/
_PROJECT_ROOT = _SCRIPT_DIR.parent.resolve()       # enterpriseGPT/

# Load .env from project root
_env_file = _PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

# Reuse phase functions from deploy_full
sys.path.insert(0, str(_SCRIPT_DIR))
from deploy_full import (  # noqa: E402
    phase1_infrastructure,
    phase2_rag_corpus,
    phase3_upload_config,
)

import vertexai  # noqa: E402


def _build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Knowledge IQ — Infra + RAG setup (Phases 1–3)",
    )
    p.add_argument("--project",  required=True,                                    help="GCP project ID")
    p.add_argument("--location", default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"), help="GCP region for Agent Engine")
    p.add_argument("--rag-location", default=os.getenv("RAG_LOCATION", "us-west1"),         help="GCP region for RAG corpus")
    p.add_argument("--bucket",   default=os.getenv("STAGING_BUCKET", "").removeprefix("gs://"),   help="GCS bucket name (without gs://)")
    p.add_argument("--corpus",   default=os.getenv("RAG_CORPUS", ""),                        help="Existing corpus resource name (blank = create new)")
    p.add_argument("--corpus-name", default="Knowledge IQ Corpus",                           help="Display name for new corpus")
    p.add_argument("--embedding-model", default=os.getenv("RAG_EMBEDDING_MODEL", "publishers/google/models/text-embedding-004"))
    p.add_argument("--seed-gcs",  default="",  help="GCS path to seed the corpus (e.g. gs://bucket/docs/)")
    p.add_argument("--chunk-size",    type=int, default=int(os.getenv("RAG_CHUNK_SIZE", "512")))
    p.add_argument("--chunk-overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", "100")))
    p.add_argument("--tools-config-gcs-uri", default=os.getenv("TOOLS_CONFIG_GCS_URI", ""))
    p.add_argument("--prompt-gcs-uri",       default=os.getenv("PROMPT_GCS_URI", ""))
    return p.parse_args()


def main() -> None:
    args = _build_args()

    if not args.bucket:
        print("ERROR: --bucket is required (or set STAGING_BUCKET in .env)")
        sys.exit(1)

    print("============================================")
    print(" Knowledge IQ — Infrastructure Setup")
    print(f" Project      : {args.project}")
    print(f" Region       : {args.location}")
    print(f" RAG Region   : {args.rag_location}")
    print(f" Bucket       : {args.bucket}")
    print("============================================")

    vertexai.init(project=args.project, location=args.location)

    # Phase 1
    bucket_uri = phase1_infrastructure(args.project, args.location, args.bucket)

    # Phase 2
    corpus_name = phase2_rag_corpus(
        project=args.project,
        location=args.location,
        rag_location=args.rag_location,
        corpus_name=args.corpus,
        corpus_display_name=args.corpus_name,
        embedding_model=args.embedding_model,
        seed_gcs=args.seed_gcs,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    # Phase 3
    config_uri, prompt_uri, _ = phase3_upload_config(
        corpus_name=corpus_name,
        bucket_name=args.bucket,
        tools_config_gcs_uri=args.tools_config_gcs_uri,
        prompt_gcs_uri=args.prompt_gcs_uri,
        embedding_model=args.embedding_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    print("")
    print("============================================")
    print(" Setup complete. Use these values for")
    print(" the agent deployment step:")
    print("")
    print(f"  RAG_CORPUS={corpus_name}")
    print(f"  TOOLS_CONFIG_GCS_URI={config_uri}")
    if prompt_uri:
        print(f"  PROMPT_GCS_URI={prompt_uri}")
    print("============================================")

    # Write corpus name to a file so GitHub Actions can read it as an output
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"rag_corpus={corpus_name}\n")
            f.write(f"tools_config_gcs_uri={config_uri}\n")
            if prompt_uri:
                f.write(f"prompt_gcs_uri={prompt_uri}\n")


if __name__ == "__main__":
    main()
