# Agent instructions

- Use INDEX.md to find the relevant skill, then read its SKILL.md and any referenced files before acting.
- Keep each skill's scripts, references, examples, and assets under its existing .claude/skills/<name> folder. Many scripts rely on nearby relative paths.
- Do not commit candidate profiles, generated job results, credentials, local run history, or output artifacts. The job-search example profile is intentionally blank; create private local profile data as needed.
- Supply API credentials and external tool configuration through the user's environment or the relevant official CLI. Never add credential values to this repository.
- project-workflows contains preserved artifacts from separate projects. Treat them as reference code and inspect their dependencies before attempting to run them.
- scheduled-tasks contains prompt templates only. It does not create or enable schedules or phone notifications.
