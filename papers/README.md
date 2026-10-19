# Daily Literature

Public Crossref paper metadata and DataCite dataset metadata, filtered by marine research topics.
No API secrets, paid subscriptions, or full-text access are required.

Run `python3 scripts/update_literature.py` from the repository root. It writes
`papers/catalog.json`, the dates page, and static daily HTML reports.
`--check` tests the topic filters; `--render-only` rebuilds pages without searching.

The first run looks through two years of indexed paper metadata and dataset search
results of all ages. Later runs use the last successful date, with a one-day overlap.
Queries inspect up to 40 Crossref records each and 50 DataCite records each. At most
40 new matching records are added per run. This bounded discovery feed is not exhaustive.
Same-day reruns append newly found records; DOI deduplication spans the entire archive.
Metadata updates on already-seen DOIs are not reposted. Topic labels are keyword matches,
not AI summaries or confirmation that a dataset contains usable CDOM/DOC measurements.
Searches use available titles and descriptions/abstract metadata; missing metadata can
cause false negatives. Partial failures are marked; complete failure preserves old reports.

To activate on GitHub, upload the workflow and script, set Settings → Pages → Source
to GitHub Actions, then run “Daily literature and Pages” under Actions. The schedule
runs at 07:17 UTC (08:17 CET / 09:17 CEST); GitHub may delay scheduled runs.
Scheduled workflows on inactive public repositories may be disabled by GitHub.
The feed updates the public website; it does not send email or phone notifications.
