# GitHub library tools

The GitHub tools use the locally installed GitHub CLI and read authentication from `gh auth login`. Set `PROJECT_SCOUT_REPOSITORY`, `PROJECT_SCOUT_BRANCH`, and (for synchronization) `PROJECT_SCOUT_VAULT_PATH` in `.env`. Do not set or commit a token in this project.

## Review before saving

`github_library.py review FILE.json` is a preview. It does not write to the repository. It returns normalized project data, a Markdown preview, and a `review_digest` bound to that content and the configured repository and branch.

After a person explicitly approves the preview, pass the exact digest and confirmation text to `save`:

```sh
python github_library.py save FILE.json --review-digest DIGEST --confirmation "确认收藏"
```

The local CLI requires an explicit confirmation argument. An application integrating this API must obtain consent from the user in its own interface; a recommendation is not consent.

## Search and updates

```sh
python github_library.py search "search terms" --category website
python github_library.py review FILE.json --action update --expected-revision CURRENT_SHA
python github_library.py update FILE.json --expected-revision CURRENT_SHA --review-digest DIGEST --confirmation "确认收藏"
```

Use the exact confirmation string and digest returned for the corresponding preview. Updates require the current file revision. Existing notes are not silently overwritten. The configured repository owner must match the authenticated GitHub CLI account, and repository visibility must be private.

## Markdown layout

The library uses `GitHub-Projects/`, `Websites/`, and `DIY-Projects/`, with one Obsidian-compatible Markdown file per collection. Required YAML properties include `id`, `title`, `category`, `url`, `source_url`, `tags`, `pricing`, `status`, `created`, and `updated`.

## Synchronization

`python vault_sync.py` runs one conservative synchronization. The vault must be a standalone Git clone whose `origin` and checked-out branch match `.env`. The program verifies private repository access before writes, stages only allowlisted files, fetches remote changes, and pushes without force. Deletions and conflicting edits stop for manual resolution; both conflict versions are backed up under the configured state directory. Use an operating-system scheduler if periodic synchronization is desired.

The CLI is not a network service and does not expose a port. It is not an MCP server and is not automatically called by ChatGPT.
