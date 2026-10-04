"""One real question through the real model. Skipped when Ollama or the export is missing."""

import json
import os
import urllib.request
from pathlib import Path

import pytest

from app.ask import AskError, OllamaClient, answer, load_examples
from app.config import Settings

pytestmark = pytest.mark.ollama

DB = Path(os.environ.get("DATA_DIR", "/data")) / "moodle.duckdb"


@pytest.fixture(scope="module")
def client():
    url = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "")
    if not model or not DB.exists():
        pytest.skip("OLLAMA_MODEL or the export is missing")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as response:
            names = {m["name"] for m in json.load(response).get("models", [])}
    except OSError as err:
        pytest.skip(f"Ollama not reachable: {type(err).__name__}")
    if model not in names:
        pytest.skip(f"{model} is not pulled; run `make init-model`")
    s = Settings(db_user="x", db_password="x", salt="x")
    return OllamaClient(url, model, s.ollama_num_ctx, "30m", 600)


def test_real_model_answers_with_guarded_sql(client):
    try:
        result = answer(
            "How many students are enrolled in each course?",
            [2, 3, 4],
            200,
            str(DB),
            client,
            load_examples(),
            6,
            30,
        )
    except AskError as err:
        if err.reason != "model_unavailable":
            raise
        # For example the model runner killed for lack of memory.
        pytest.skip(f"model could not run: {err.message}")
    assert result.sql.lower().lstrip().startswith(("select", "with"))
    assert result.rows
    assert result.attempts in (1, 2)
