"""Publish the dashboard to the Hugging Face Space (Docker SDK).

    hf auth login                    # once, with a token that has write access
    python scripts/publish_space.py  # creates the Space if needed, uploads one commit

Hugging Face only creates new Spaces with the gradio, docker or static SDKs, so the Space
runs the repo's own Dockerfile. As of September 2026 hosting a new Docker Space needs a
paid (PRO) account: create_repo answers 402 on a free account, and this script says so
instead of tracing back. Uploads the Space card, Dockerfile, requirements,
src/dashboard/app.py and data/summary/*. Prints the Space URL. Files already in the
Space that are not in this set are left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi
from huggingface_hub.errors import HfHubHTTPError

ROOT = Path(__file__).resolve().parent.parent
SPACE = "bass990/stackoverflow-causal-retention"


def files() -> dict[str, Path]:
    out = {
        "README.md": ROOT / "huggingface-spaces" / "README.md",
        "Dockerfile": ROOT / "Dockerfile",
        "requirements-dashboard.txt": ROOT / "requirements-dashboard.txt",
        "src/dashboard/app.py": ROOT / "src" / "dashboard" / "app.py",
    }
    for p in sorted((ROOT / "data" / "summary").iterdir()):
        out[f"data/summary/{p.name}"] = p
    return out


def main() -> int:
    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception as exc:  # noqa: BLE001
        print(f"not logged in to Hugging Face ({str(exc)[:80]}). Run: hf auth login")
        return 1
    fs = files()
    missing = [p for p in fs.values() if not p.exists()]
    if missing:
        print("missing:", *missing, sep="\n  ")
        return 1
    try:
        api.create_repo(repo_id=SPACE, repo_type="space", space_sdk="docker", exist_ok=True)
    except HfHubHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 402:
            print("Hugging Face refused to create the Space (402): hosting a new Docker Space "
                  "requires a PRO subscription. Nothing was uploaded.")
            return 2
        raise
    ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(v)) for k, v in fs.items()]
    info = api.create_commit(repo_id=SPACE, repo_type="space", operations=ops,
                             commit_message="Dashboard from committed summaries (data/summary), Docker SDK")
    print(f"published {len(ops)} files as {user}: {info.commit_url}\nhttps://huggingface.co/spaces/{SPACE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
