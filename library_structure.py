"""Non-destructive vault scaffolding. Explicit deployment command, not collection."""
from pathlib import Path
from github_library import GitHubStore, FOLDERS, LibraryError

README_ADDITION = '''

<!-- project-scout-library-guide-v1 -->
## Using this private collection library

Open [Home.md](Home.md). Each collection is a Markdown file with YAML properties and can be opened in Obsidian.

- `GitHub-Projects/`: GitHub repositories and open-source projects.
- `Websites/`: websites and online tools.
- `DIY-Projects/`: physical projects and build instructions.
- `Attachments/`: optional, manually added assets.
- `Templates/`: note templates for the three categories.

Project Scout's review and a user's explicit save confirmation are separate steps. The ChatGPT Skill, GitHub Connector, and this local Python application are separate components. Connecting them is a user-configured step; installing this repository does not grant ChatGPT access.

## 笔记与修改

Keep `id`, `created`, and the category folder stable. Existing projects with the same ID, canonical URL, or GitHub repository are treated as duplicates and are not overwritten automatically. Updates require the current note revision to avoid overwriting concurrent edits.

Failed or uncertain writes are not reported as successful. Never put tokens, passwords, `.env` files, machine-specific configuration, or credential-bearing URLs in notes. Private repository access control is not end-to-end encryption.

## Mobile reading and synchronization

GitHub does not automatically sync a repository into Obsidian. Choose and configure an iOS Git workflow separately; test it with a backup before editing on multiple devices.

Do not run multiple sync services against the same vault at once. Pull before editing and push after editing.
'''

HOME = '''# Project Scout 收藏库

这里仅存放确认收藏后的项目。从 Obsidian 文件列表按以下目录浏览，或使用 Properties 搜索，例如 `[category:github]`。

## Categories

- [GitHub Projects](GitHub-Projects/)
- [Websites](Websites/)
- [DIY Projects](DIY-Projects/)
- [Templates](Templates/)

Use Obsidian's file list or search; no community plugin is required.

## Collection workflow

Research and review → inspect use, cost, examples, and limitations → explicit user confirmation → save → read-back verification.

Recommendations are not saved automatically. Existing SQLite data is not imported automatically.
'''


def template(category):
    return '''---
id: "replace-with-stable-id"
title: "Project title"
category: "''' + category + '''"
url: "https://example.com/project"
source_url: ""
tags: []
pricing: "Not verified"
status: "want-to-try"
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
github_url: ""
---

# Project title

## What is it useful for?

Explain the core function, how it works, the problem it solves, and notable features.

## Pricing

Describe verified pricing or material costs. Do not guess.

## Practical things to try

- Task and expected result.
- Task and expected result.
- Task and expected result.

## Limitations

- Important limitation.
- Important limitation.

## Collection recommendation

Recommended / Maybe / Not recommended, with a short reason.

## Official site and references

- Verified official or original source link.
'''


def structure_files(existing_readme):
    result = {"Home.md": HOME}
    if "<!-- project-scout-library-guide-v1 -->" not in existing_readme:
        result["README.md"] = existing_readme.rstrip() + README_ADDITION
    for category, folder in FOLDERS.items():
        result[folder + "/.gitkeep"] = ""
        result["Templates/" + category + ".md"] = template(category)
    result["Attachments/.gitkeep"] = ""
    return result


def bootstrap(store=None):
    store = store or GitHubStore()
    snap = store.snapshot()
    readme = store.read(snap["files"]["README.md"]) if "README.md" in snap["files"] else "# Project Scout Library\n"
    wanted = structure_files(readme)
    files = {p: c for p, c in wanted.items() if p == "README.md" or p not in snap["files"]}
    if not files:
        return {"status": "existing", "private": True}
    commit = store.commit_files(snap, files, "Initialize Project Scout Obsidian library")
    checked = store.snapshot()
    for path, content in files.items():
        if path not in checked["files"] or store.read(checked["files"][path]) != content:
            raise LibraryError("目录初始化回读失败：" + path)
    return {"status": "created", "private": True, "commit": commit, "files": list(files)}


if __name__ == "__main__":
    import json
    print(json.dumps(bootstrap(), ensure_ascii=False, indent=2))
