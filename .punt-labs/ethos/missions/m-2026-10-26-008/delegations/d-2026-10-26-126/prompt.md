You are the worker on ethos mission m-2026-10-26-008. Read the contract first with `ethos mission show m-2026-10-26-008`. The contract file is ~/Coding/punt-labs/.tmp/missions/scrub-json-safe.yaml.

Summary: `.bin/session/scrub.py` corrupts ethos audit chunks (.jsonl). Its email regex matches inside a JSON `<` escape, leaving `\[REDACTED:email]`, which is invalid JSON. Ethos's pre-commit seal then blocks every commit in that repo.
1. Write failing tests first.
2. Make .jsonl scrubbing structurally JSON-safe: parse each line, scrub the string values, re-serialize.
3. Keep plain-text behavior unchanged.
4. Report, with ethos file:line evidence, whether rewriting sealed audit chunks is safe at all. Report this; do not decide it.

Work only in ~/Coding/punt-labs/.claude/worktrees/scrub-json-safe (branch fix/scrub-json-safe). Use absolute paths and one shell command per Bash call.

Commit on your branch. Do not push, and do not touch PRs or merge; the leader does that. Stage only the files you changed. Submit your result to the mission when done, and report the commits, test output, and your item-4 findings.