# ChatGPT integration boundaries

Project Scout can be used alongside ChatGPT, but this repository does not connect to a ChatGPT account.

- A ChatGPT Skill provides instructions for researching and reviewing projects.
- A GitHub Connector provides account-authorized GitHub tools inside ChatGPT.
- This local Python application provides SQLite, Streamlit, GitHub CLI, and Git synchronization features on the user's computer.

These components have separate installation and authorization flows. A Skill alone cannot call this local code. A GitHub Connector must be enabled and authorized for the intended repository. Do not assume that installing this repository connects ChatGPT to a computer, SQLite file, or GitHub repository.

For a future custom integration, expose a deliberate API and implement authentication, authorization, user confirmation, input validation, duplicate handling, concurrency checks, and read-back verification. Do not expose a local service to the public Internet as a shortcut. The current repository contains no MCP server or hosted API.

The GitHub library CLI separates preview from persistence. A host application should present the exact project to be saved and ask for explicit confirmation after the review. It should then pass the matching review digest to the save/update operation and report success only after the library read-back is verified.
