"""Environment-backed configuration shared by the local app and GitHub tools."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)


def project_path(variable: str, default: str) -> Path:
    value = os.getenv(variable, default).strip()
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def configured_repository() -> str:
    repository = os.getenv("PROJECT_SCOUT_REPOSITORY", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError(
            "Set PROJECT_SCOUT_REPOSITORY in .env to your GitHub owner/repository."
        )
    return repository


def configured_branch() -> str:
    branch = os.getenv("PROJECT_SCOUT_BRANCH", "main").strip()
    if not branch or branch.startswith("-") or ".." in branch or " " in branch:
        raise RuntimeError("PROJECT_SCOUT_BRANCH is not a valid branch name.")
    return branch


def configured_remote() -> str:
    return f"https://github.com/{configured_repository()}.git"


def git_executable() -> str:
    value = os.getenv("PROJECT_SCOUT_GIT_EXECUTABLE", "").strip()
    executable = value or shutil.which("git")
    if not executable:
        raise RuntimeError("Git was not found. Install Git and add it to PATH.")
    return executable
