# Skill index

Purpose summaries come from each skill's SKILL.md. Code counts include source and test files; four skills are primarily reference documents. The media, fonts, and reference material stay in their skill folders.

## Finance and market research

| Skill | Purpose | Code files |
|---|---|---:|
| [earnings-calendar](.claude/skills/earnings-calendar/SKILL.md) | Earnings schedules, impact ratings, estimates, actuals, and results. | 2 |
| [economic-calendar](.claude/skills/economic-calendar/SKILL.md) | Economic releases, central-bank events, and actual-versus-consensus comparisons. | 2 |
| [fair-value](.claude/skills/fair-value/SKILL.md) | Historical P/E valuation, forward EPS bands, and backtesting. | 4 |
| [finviz-earnings](.claude/skills/finviz-earnings/SKILL.md) | Company earnings history, estimates, revisions, valuation, and report-day price behavior. | 1 |
| [finviz-market-sentiment](.claude/skills/finviz-market-sentiment/SKILL.md) | Scores news headlines, produces a directional sentiment index, and renders reports. | 6 |
| [finviz-news](.claude/skills/finviz-news/SKILL.md) | Saves Finviz news feeds as dated JSON. | 1 |
| [stock-forecast](.claude/skills/stock-forecast/SKILL.md) | Collects data and produces a full stock forecast dashboard with scoring and validation. | 17 |
| [stockanalysis](.claude/skills/stockanalysis/SKILL.md) | Retrieves fundamentals, transcripts, estimates, filings, and related company data. | 4 |
| [yahoo-finance](.claude/skills/yahoo-finance/SKILL.md) | Retrieves quotes, history, fundamentals, and ticker lookups. | 1 |

## Video, animation, and media

| Skill | Purpose | Code files |
|---|---|---:|
| [faceless-explainer](.claude/skills/faceless-explainer/SKILL.md) | Turns a topic or brief into a scene-based explainer video. | 17 |
| [figma](.claude/skills/figma/SKILL.md) | Imports Figma designs and assets into HyperFrames. | 1 |
| [general-video](.claude/skills/general-video/SKILL.md) | Guides custom and multi-scene HyperFrames builds. | 2 |
| [hyperframes](.claude/skills/hyperframes/SKILL.md) | Routes HyperFrames creation, editing, validation, rendering, and publishing. | 0 |
| [hyperframes-animation](.claude/skills/hyperframes-animation/SKILL.md) | Motion rules, animation blueprints, transitions, and runtime adapters. | 6 |
| [hyperframes-audio](.claude/skills/hyperframes-audio/SKILL.md) | Mixes and automates audio already placed in a composition. | 2 |
| [hyperframes-cli](.claude/skills/hyperframes-cli/SKILL.md) | Documents HyperFrames CLI build, preview, validation, and render workflows. | 0 |
| [hyperframes-core](.claude/skills/hyperframes-core/SKILL.md) | Defines composition structure, timing, tracks, media behavior, and validation. | 1 |
| [hyperframes-creative](.claude/skills/hyperframes-creative/SKILL.md) | Design direction, palettes, typography, narration, story beats, and composition patterns. | 4 |
| [hyperframes-keyframes](.claude/skills/hyperframes-keyframes/SKILL.md) | Camera moves, zooms, reframing, keyframe animation, and diagnostics. | 0 |
| [hyperframes-registry](.claude/skills/hyperframes-registry/SKILL.md) | Finds, installs, and wires reusable HyperFrames blocks and components. | 0 |
| [media-use](.claude/skills/media-use/SKILL.md) | Media sourcing and generation, audio, voice, transcription, grading, and media operations. | 108 |

## Job search

| Skill | Purpose | Code files |
|---|---|---:|
| [job-search](.claude/skills/job-search/SKILL.md) | Finds postings on company ATS systems, checks requirements and fit, verifies links, and creates an HTML list. | 16 |

The repository contains **195 skill code files**, including **57 test files**. The largest is media-use. Four skills are reference-only or routing-oriented. There are also 22 separate workflow scripts under project-workflows and two task prompt templates under scheduled-tasks.

## Reusable components worth knowing

- media-use is a shared asset and audio toolkit. It includes provider adapters, SFX and music assets, LUT references, tests, and credits.
- HyperFrames is a documentation-heavy video toolchain. Its animation skill contains many blueprints, rules, and reference guides alongside a small number of helper modules.
- stock-forecast contains a data collection, model, evidence, rendering, and validation pipeline plus ticker-specific example specs.
- job-search keeps a starter ATS-board dataset and a generic profile schema; prior personal profile and output data were excluded.
