# Packaging notes

## Included

- All 22 skill directories under .claude/skills, including their SKILL.md files, references, examples, source scripts, test source, and bundled assets.
- The job-search ATS board seed list and a blank candidate profile schema.
- Two prompt templates for the pre-market and afternoon market-sentiment routines.
- Twenty-two project workflow JavaScript files, stored separately by project name.
- Markdown indexes and general agent guidance.

## Left out

- Python bytecode caches and the old render.py backup copy.
- The job-search candidate profile, active-profile file, previous job listings, description caches, and generated result files. A blank template is provided instead, and ignore rules protect future local data.
- Machine-specific global Claude instructions and configuration, which are not part of the skill library and contain local environment details.
- API credentials, account credentials, and external runtimes. No credential values should be stored in this repository.

## Portability edits

The job-search profile template has no candidate values. Its eligibility, location, title, company-exclusion, and skill scoring paths read from that profile. Candidate-specific names, dates, and result notes were removed from the guide and helper messages. The existing market coverage remains US-oriented and centered on software roles; non-US and non-engineering searches need filter and board-list changes.

The saved sentiment task prompts have machine-specific paths replaced with repository-relative skill paths and a SENTIMENT_RUNS_DIR placeholder. They remain prompt templates, not active schedules.

## Counts

- 22 skill folders, 195 code/test files, and 57 test files.
- 22 archived project workflow scripts across Nclexmap, ConquerRTS, Zen Racer, and a TQQQ study.
- Two sentiment task prompt templates.
