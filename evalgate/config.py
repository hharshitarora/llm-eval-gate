"""Environment configuration.

Nothing here is required for the default hermetic path. A key is only loaded
when something actually asks for a live model, so `pytest` and the mock gate
run on a machine that has never seen an OpenAI account.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_JUDGE_MODEL = "gpt-4o-mini"


def judge_model() -> str:
    return os.environ.get("EVALGATE_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)


def require_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set, which is only needed for --judge llm or "
            "--adapter triage. The default hermetic run needs no key:\n"
            "    python -m evalgate run --adapter mock --judge heuristic"
        )
    return key
