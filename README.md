# Project Scout

Project Scout is a personal project research and collection toolkit. It includes a local Python and SQLite catalog, a Streamlit interface, and optional tools for saving reviewed project notes as Markdown in a GitHub repository that can be opened with Obsidian.

The code in this repository does not automatically research projects, connect ChatGPT, or grant access to any GitHub account. Those are separate components that users configure themselves.

## Features

- Store project names, descriptions, use cases, instructions, URLs, prices, categories, tags, and collection dates in SQLite.
- Browse, search, add, edit, and delete records in a Chinese-language Streamlit interface.
- Import JSON with validation and deterministic duplicate detection.
- Preview structured GitHub library notes before saving. Save and update operations require an explicit confirmation argument, use duplicate checks, and verify writes by reading the note back.
- Synchronize a configured Obsidian vault with a GitHub repository using Git, without force-pushing or automatically propagating deletions.
- Use Markdown templates and a native Obsidian Bases file for GitHub projects, websites, and DIY projects.

## Workflow

1. Research and review a project using a process of your choice.
2. Inspect the result and decide whether to keep it.
3. Add it to the local SQLite catalog, or prepare a structured project JSON for the GitHub library tools.
4. For GitHub storage, preview the note first and explicitly confirm before invoking save. The local CLI cannot infer user consent from a review recommendation.
5. Read the saved Markdown note back to verify it. Open the vault in Obsidian and configure device synchronization separately.

### Collection categories

- **GitHub projects:** repository purpose, setup, license, maintenance, and limitations.
- **Websites:** service purpose, access requirements, pricing, and practical uses.
- **DIY projects:** expected result, materials, cost, time, difficulty, and safety considerations.

This application stores the information supplied to it; it does not verify claims or produce a research review by itself.

## Components and architecture

- `collector.py` contains SQLite schema management, validation, duplicate detection, JSON import, and a command-line import interface.
- `app.py` is the Streamlit administration interface.
- `github_library.py` provides a GitHub CLI-backed Markdown save/search/update interface.
- `vault_sync.py` performs a conservative two-way Git synchronization for Markdown, Bases, and selected attachments.
- `library_structure.py` can initialize missing library folders and templates without replacing existing content.
- `integrations.py` contains interface contracts for possible research and spreadsheet adapters; it does not make network requests.
- `obsidian/` contains reusable note templates and a native Bases configuration.

### ChatGPT Skill, GitHub Connector, and local application

These are three separate things:

1. A **ChatGPT Skill** supplies review instructions. It is not installed or changed by this Python repository.
2. A **GitHub Connector** is an account-authorized ChatGPT integration. Users must enable and authorize it for the repository themselves.
3. The **local Python application** runs on the user's computer and uses the locally installed GitHub CLI for its GitHub operations.

Installing this code does not connect these components. This repository does not include an MCP server, public web service, or automatic ChatGPT-to-Python bridge. The user must independently configure each connection and retain an explicit confirmation step before saving a review.

## Requirements

- Python 3.11 or newer.
- Git for GitHub Markdown storage and vault synchronization.
- GitHub CLI (`gh`) logged into an account that can access the configured private repository, if using the GitHub features.
- Obsidian is optional and is not required for the SQLite web app.

Official downloads: [Git](https://git-scm.com/downloads), [GitHub CLI](https://cli.github.com/), and [Obsidian](https://obsidian.md/download).

## Installation

From a fresh checkout, create a virtual environment and install the pinned direct dependencies:

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

If `python` is not recognized, use the full path to a Python 3.11+ executable when creating the environment.

### macOS or Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Streamlit prints the local URL when it starts. Stop the server with `Ctrl+C`. The supplied Streamlit configuration binds to loopback and disables usage statistics.

For optional configuration, copy `.env.example` to `.env` and edit only the values needed for your setup. In PowerShell run `Copy-Item .env.example .env`; in macOS/Linux run `cp .env.example .env`. `.env` is ignored by Git. The SQLite database defaults to `tools.db` in the project directory; set `PROJECT_SCOUT_DB_PATH` to change it. Relative paths in `.env` are relative to the project directory.

## Use the local catalog

Add and edit records in the Streamlit page. To import the example JSON:

```sh
python collector.py --import-json examples/tools.json
```

The example is a placeholder record. Replace it with your own data before importing. JSON records accept `name` (required), `description`, `purpose`, `usage`, `website`, `github`, `source_url`, `price`, `category`, `tags`, and `collected_date`. Invalid batches are rejected atomically. Matching normalized names, websites, or GitHub URLs are skipped as duplicates rather than replacing existing notes.

## Optional GitHub Markdown library

1. Install Git and GitHub CLI from their official sources, then authenticate with the GitHub CLI using its documented browser flow. Do not paste credentials into project files.
2. Create or select a **private** repository that you control.
3. Copy `.env.example` to `.env` and set `PROJECT_SCOUT_REPOSITORY` to `owner/repository`. The repository must remain private for writes; the client fails closed if the authenticated account, repository identity, or private visibility do not match.
4. Prepare your collection vault as a separate Git clone of that repository. Set `PROJECT_SCOUT_VAULT_PATH` to its local path.
5. Preview a structured project file before saving:

   ```sh
   python github_library.py review examples/reviewed-project.template.json
   ```

   The preview returns a digest bound to the reviewed content, repository, branch, and action. Only pass that digest and an explicit `--confirmation` value after reviewing the preview. See [docs/github-library.md](docs/github-library.md) for the exact command contract and recovery behavior.

6. Run a one-shot vault synchronization with `python vault_sync.py`. To synchronize periodically, configure your operating system's task scheduler to run that command while you are signed in. For Windows, see [the Task Scheduler guide](docs/windows-scheduling.md). This repository does not create a scheduled task automatically.

Synchronization checks the configured private repository, uses an allowlist of Markdown, Bases, and selected attachment files, and will not force-push. It stops on deletions or conflicts and preserves both sides for review. Keep the vault in its own Git clone, outside this source-code checkout.

## Obsidian and GitHub

The `obsidian/` directory contains note templates and `Collections.base`. Copy these into the root of your Obsidian vault alongside `GitHub-Projects/`, `Websites/`, and `DIY-Projects/`. The Bases file uses only Obsidian's built-in feature. GitHub is the Markdown storage destination; Obsidian is a reader/editor. Neither automatically synchronizes a phone unless a separate iOS Git workflow is configured.

## Privacy and security

- The SQLite database, `.env`, virtual environments, local state, and Obsidian vault are excluded by `.gitignore`.
- No personal collection notes, private vault history, account tokens, machine logs, or credential files are included in the release source.
- GitHub operations use the GitHub CLI's own authentication storage. The application does not accept or save GitHub tokens in its configuration.
- Git synchronization does not use force push, hard reset, clean, rebase, or automatic deletion propagation.
- A GitHub private repository is access-controlled, not end-to-end encrypted. Anyone with repository access can read its contents.
- Back up the database and vault before modifying them. Review every note before saving it to a remote repository.

## Tests

Run the test suite from the repository root:

```sh
python -m unittest discover -s tests -v
```

Tests use temporary databases, fake GitHub API responses, and local temporary Git repositories. They do not contact GitHub or write to a configured collection library.

## Limitations

- The local app does not search the web or generate research reviews.
- ChatGPT access, the GitHub Connector, and any Skill must be configured separately.
- There is no hosted API or MCP server in this project.
- GitHub features require a separate private repository and authenticated GitHub CLI.
- Phone synchronization is not configured by this application.
- Duplicate detection uses normalized names and URLs; it does not determine semantic equivalence.

## License

Project Scout's original code is released under the MIT License. Third-party packages remain under their own licenses; see [Third-party notices](THIRD_PARTY_NOTICES.md).
