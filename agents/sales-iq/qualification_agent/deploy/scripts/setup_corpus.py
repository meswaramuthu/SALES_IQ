#!/usr/bin/env python3
"""Bootstrap script — create a Vertex AI RAG corpus and optionally seed it with documents.

Run this ONCE before deploying the agent to set up your knowledge base.
The script prints the corpus resource name; copy it into your tools_config.json
(or .env) so the agent can use it.

Usage examples:
    # Create an empty corpus (English, default embedding model)
    uv run python scripts/setup_corpus.py --name "Knowledge IQ Docs"

    # Create and seed from a GCS folder
    uv run python scripts/setup_corpus.py \\
        --name "Engineering Runbooks" \\
        --description "Internal engineering documentation" \\
        --seed-gcs gs://my-bucket/docs/

    # Create and seed from a single URL
    uv run python scripts/setup_corpus.py \\
        --name "Policy Docs" \\
        --seed-url https://example.com/company-policy.pdf

    # Use multilingual embedding model
    uv run python scripts/setup_corpus.py \\
        --name "Global Knowledge Base" \\
        --embedding-model publishers/google/models/text-multilingual-embedding-002
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

import requests
import vertexai
from dotenv import load_dotenv, set_key
from vertexai.preview import rag

load_dotenv()

_DEFAULT_MODEL = "publishers/google/models/text-embedding-004"
_ENV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))


def _init() -> None:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    if not project:
        sys.exit("Error: GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env and fill it in.")
    vertexai.init(project=project, location=location)
    print(f"Initialized Vertex AI: project={project}, location={location}")


def _create_corpus(name: str, description: str, model: str) -> rag.RagCorpus:
    """Create corpus, or return existing one with the same display_name."""
    for existing in rag.list_corpora():
        if existing.display_name == name:
            print(f"Found existing corpus: {existing.name}")
            return existing

    corpus = rag.create_corpus(
        display_name=name,
        description=description or name,
        embedding_model_config=rag.EmbeddingModelConfig(publisher_model=model),
    )
    print(f"Created corpus: {corpus.name}")
    return corpus


def _seed_gcs(corpus_name: str, gcs_path: str, chunk_size: int, chunk_overlap: int) -> None:
    print(f"Importing from GCS: {gcs_path} …")
    response = rag.import_files(
        corpus_name=corpus_name,
        paths=[gcs_path],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    print(f"  Imported: {response.imported_rag_files_count} | Failed: {response.failed_rag_files_count}")


def _seed_url(corpus_name: str, url: str, display_name: str) -> None:
    print(f"Downloading {url} …")
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    import re
    _, ext = os.path.splitext(re.sub(r"\?.*", "", url))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"seed{ext or '.pdf'}")
        with open(path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        print(f"Uploading {display_name} …")
        rag_file = rag.upload_file(
            corpus_name=corpus_name,
            path=path,
            display_name=display_name or os.path.basename(url),
            description=f"Seeded from {url}",
        )
    print(f"  Uploaded: {rag_file.name}")


def _list_files(corpus_name: str) -> None:
    files = list(rag.list_files(corpus_name=corpus_name))
    print(f"\nIndexed files ({len(files)} total):")
    for f in files:
        print(f"  {f.display_name}  —  {f.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and optionally seed a Vertex AI RAG corpus")
    parser.add_argument("--name", required=True, help="Corpus display name")
    parser.add_argument("--description", default="", help="Corpus description")
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("RAG_EMBEDDING_MODEL", _DEFAULT_MODEL),
        help="Publisher model path for embeddings",
    )
    parser.add_argument("--chunk-size", type=int, default=512, help="Chunk token size (default 512)")
    parser.add_argument("--chunk-overlap", type=int, default=100, help="Chunk overlap tokens (default 100)")
    parser.add_argument("--seed-gcs", default="", help="GCS path to import (e.g. gs://bucket/folder/)")
    parser.add_argument("--seed-url", default="", help="Public URL of a document to upload")
    parser.add_argument("--seed-url-name", default="", help="Display name for --seed-url document")
    parser.add_argument(
        "--update-env",
        action="store_true",
        default=True,
        help="Write corpus resource name to .env as RAG_CORPUS (default: true)",
    )
    args = parser.parse_args()

    _init()
    corpus = _create_corpus(args.name, args.description, args.embedding_model)

    if args.seed_gcs:
        _seed_gcs(corpus.name, args.seed_gcs, args.chunk_size, args.chunk_overlap)

    if args.seed_url:
        _seed_url(corpus.name, args.seed_url, args.seed_url_name)

    _list_files(corpus.name)

    if args.update_env:
        try:
            set_key(_ENV_FILE, "RAG_CORPUS", corpus.name)
            print(f"\nUpdated RAG_CORPUS in .env: {corpus.name}")
        except Exception as exc:
            print(f"\nWarning: could not write .env ({exc})")

    print(f"\n{'='*60}")
    print(f"Corpus resource name: {corpus.name}")
    print(f"Add to tools_config.json under rag.config.corpus")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
