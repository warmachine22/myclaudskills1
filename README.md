# myclaudskills1

A private, portable library of the 22 Claude Code skills found on this computer, with their helper code, references, tests, and required local assets. The skill folders keep their original internal structure so scripts can find nearby resources.

## Start here

- Read INDEX.md to choose a skill.
- Read that skill's SKILL.md before using it. Follow links to its references and keep its scripts and assets beside it.
- Read AGENTS.md for instructions intended for other AI agents working in this repository.
- Read MIGRATION_NOTES.md for the packaging decisions and known scope limits.

## Layout

- .claude/skills/ — the 22 reusable skills and their related files.
- project-workflows/ — 22 JavaScript workflow artifacts saved in Claude project records; archived by original project and not guaranteed to run without those projects.
- scheduled-tasks/ — two portable prompt templates for the Finviz sentiment runs. They are not registered schedules.

## Using a skill

When this repository is open in Claude Code, skills live in its standard .claude/skills location. To install one globally, copy the selected skill folder from .claude/skills into the user's Claude Code skills directory, keeping the skill folder name intact. Other agents can read the same SKILL.md and follow adjacent references and scripts.

The scripts and media are included, but each workflow may call external CLIs, libraries, APIs, or services. Check its SKILL.md and code before running it. Configure required credentials outside Git; no API keys or account credentials belong in this repository.

## Personal data and generated files

The job-search pipeline has a blank profile template. It does not include a real candidate profile, active-profile selector, or prior job listings. Copy the template locally and keep profile and run data untracked; ignore rules are included. The checked-in ATS board list is a reusable starting snapshot and can become stale.

## Scope

This is an inventory and preservation package, not a full installation of every skill's external runtime. The job-search pipeline is profile-driven but its source coverage and title heuristics still target US software-engineering roles; adjust those filters and board data for a different market or occupation. Scheduled-task prompts and project workflows require separate runtime configuration.
