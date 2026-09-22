# Sentiment task templates

These are saved prompt templates corresponding to the pre-market and afternoon Finviz market-sentiment routines. They are not scheduled jobs and have not been enabled by this repository.

Before reusing one, replace each <SENTIMENT_RUNS_DIR> placeholder with the path of a writable local directory and resolve the skill path from repository root. The prompts score headlines, update a dashboard/report, and request a phone push; actual scheduling, artifact hosting, and notification delivery require the user's existing scheduler and external service configuration.
