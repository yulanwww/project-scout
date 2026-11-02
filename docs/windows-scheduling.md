# Optional Windows scheduled synchronization

`vault_sync.py` runs one synchronization and exits. To repeat it, create a task in Windows Task Scheduler after you have configured `.env`, installed Git/GitHub CLI, authenticated with `gh`, and cloned the private library into a separate vault.

1. Open **Task Scheduler** and choose **Create Basic Task**.
2. Set the trigger to **When I log on**.
3. Choose **Start a program**.
4. Set **Program/script** to the full path of the project's `.venv\Scripts\pythonw.exe`.
5. Set **Add arguments** to the full path of `vault_sync.py` in quotes.
6. Set **Start in** to the project directory.
7. In the task's trigger settings, enable **Repeat task every 5 minutes** for **Indefinitely**.
8. In task properties, select **Run only when user is logged on** so GitHub CLI can use the signed-in user's credential store.

The task only synchronizes while the computer is on and the account is signed in. It does not open a network listener. Review `.local/sync/status.json` after a failure. Conflicts, local deletions, and remote deletions stop for review rather than being resolved destructively.
