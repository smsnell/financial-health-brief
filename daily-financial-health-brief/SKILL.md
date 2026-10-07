---
name: daily-financial-health-brief
description: Prepare a traceable draft daily financial health brief from live view-only transaction, budget and revenue Google Sheets. Use for daily posted activity comparisons, monthly budget reconciliation, revenue snapshot comparisons and unresolved financial items requiring human review.
compatibility: Requires Python 3.10+ on Linux, macOS or WSL, HTTPS network access to docs.google.com and Google export hosts, and a writable output directory. No third-party runtime packages required.
---

# Daily financial health brief

Prepare Quillhaven Academy's Finance and Operations Manager's draft for the Operations Owner. All external access is read-only. The Operations Owner makes spending, escalation and dispute decisions.

## Operator workflow

1. Obtain the three current view-only Google Sheets URLs, the reporting date and the prior business date from the manager. Read [business rules](references/business-rules.md) before interpreting findings. Normal mode uses Operations' completeness confirmation through `--ledger-context`; its format and period scope are in [source contracts](references/source-contracts.md). A fetched row count alone is not confirmation. The user has instructed this implementation to proceed with available evidence for now: use the explicit provisional command below while confirmation remains unavailable. This exception is recorded in the draft and does not claim compliance with interview-7's completeness prerequisite. Use specified dates; the command does not infer holidays or business days.
2. From this skill directory, run the command below. Replace URLs and dates for a new manager request. The source order is interchangeable; roles are identified from headers. Network access must be allowed by the operator's environment.
3. Confirm exit status 0 and `PROVISIONAL DRAFT READY` (or `DRAFT READY` in confirmed mode). Review all three `SOURCE` metadata records, then open `../deliverables/report.md`. In provisional mode, `LEDGER_CONTEXT null` and the prominent unconfirmed-coverage warning must be present; ledger totals and comparisons describe fetched records only and ledger materiality is withheld. Check the five signed daily figures, budget and snapshot evidence, and full unresolved queue. Hand the draft to the Operations Owner for review; do not execute financial decisions or contact source owners automatically.
4. On a nonzero exit, use stderr to identify the failed access, output cleanup or evidence check. The report is marked unavailable before CSV cleanup. Each CSV is removed independently; a failed deletion triggers an attempt to replace it with an unmistakable unavailable marker. Cleanup errors stop publication and name the affected paths. Resolve filesystem issues before rerunning; request clarification from Operations for ledger issues or Finance for budget/revenue issues. Rerun the same full command after resolution; every rerun freshly reads all three sources. An overlapping invocation leaves the active run's output ownership intact.

## One end-to-end command

Runtime: Python 3.10+ on Linux, macOS or WSL, with HTTPS access to the supplied view-only Sheets and a writable output directory. Uses only the standard library (`urllib`, `csv`, `decimal`, `fcntl` and related modules). No install step, API key, connector login or third-party runtime dependency. Tested on Python 3.14.4; the latest provisional live run of the disclosed sources took approximately 3.1 seconds. Network latency varies; each request has a 30-second timeout and a 10 MB input limit.

```bash
python3 scripts/build_brief.py \
  --source-url 'https://docs.google.com/spreadsheets/d/16HhjfR9uG1oUwSFNjQvAvU9Q9gVjzxL0ufBzTJe82v8' \
  --source-url 'https://docs.google.com/spreadsheets/d/1pnHBrxWvZBDIQItyxhmaSUZBxF8VMYqo_fyN7JtgyA4' \
  --source-url 'https://docs.google.com/spreadsheets/d/1DToTpZtuwtVIdCPethZRe4T-y6mxGpWuivWSmR2XZt4' \
  --report-date 2026-08-11 \
  --prior-business-date 2026-08-10 \
  --allow-unconfirmed-ledger
```

This command produces a provisional draft under the user's instruction to make do with available evidence. For the interview's confirmed workflow, replace `--allow-unconfirmed-ledger` with `--ledger-context ../references/ledger-context.json` after obtaining actual Operations evidence. With neither option, publication fails. A supplied context must validate even when provisional mode is enabled; conflicting or malformed evidence cannot be bypassed. No production confirmation is bundled or inferred.

Outputs: `../deliverables/normalized/transactions.csv`, `budget.csv`, `revenue.csv`, and `../deliverables/report.md`. The CSVs preserve all fetched records; their population coverage must be interpreted with the accompanying report. `--output-dir` and `--ledger-context` are resolved from the skill root, independent of the caller's working directory. Use a separate output directory for exploratory dates so you do not replace the manager's current draft. `--help` displays options without changing deliverables.

## Evidence boundaries

The current sources each contain one visible tab. The executable discovers its name and numeric identity through Google's view-only page and freshly reads the whole CSV export. Multi-tab workbooks or changed page markup fail with a clarification request rather than silently selecting a tab. Cached or manually downloaded files are never accepted as primary runtime inputs.

Exact calculations and output ordering are deterministic for unchanged business inputs and dates. Fetch timestamps vary each run. Source versions are copied from business fields; a content hash provides separate integrity evidence.

Explicit unknown pending/disputed amounts, unmapped categories and missing snapshot comparators remain visible; affected conclusions are withheld. Missing ledger completeness context stops normal mode. The explicit provisional exception publishes observed-record arithmetic with unconfirmed coverage and withholds all ledger materiality decisions. Negative comparison baselines retain signed differences but withhold percentages and materiality, recording the undefined rule as a review item. Fetch/schema conflicts and conflicting supplied completeness evidence still stop publication and invalidate prior outputs. Source-owner confirmation must match the live spreadsheet identity, business version, requested period and transaction count; its values come independently from Operations.

Skill format follows the [Agent Skills specification](https://agentskills.io/specification). Business rules come from the repository's DESIGN.md and the final unmodified interview export, interviews/interview-7.md.
