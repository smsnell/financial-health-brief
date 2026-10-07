# Source contracts and failure recovery

The command requires exactly three distinct Google Sheets identities. It reads the view-only page, discovers exactly one tab, then reads its full CSV export over HTTPS with no-cache headers. It has no offline input option or stored primary source copies. Row counts exclude the header and wholly blank rows. Each nonblank row must conform to the identified role; rows are not silently dropped.

## Role identification and schemas

Headers are matched by meaning using the following explicit field contracts, after trimming whitespace and lowercasing header names. Column order, spreadsheet titles, URLs, and tab titles do not determine source role. A role is accepted only when all required fields are present and exactly one schema matches. Unrecognized header aliases need clarification rather than guessing.

- Transactions: transaction_id, date, account, category, description, amount, currency, status, source, source_version, amount_status.
- Budget: period, category, budget_amount, currency, owner, review_rule, source, source_version.
- Revenue: date, source, metric, value, currency, source_version.

Output retains these fields, every extra source column, and source_spreadsheet_id, source_tab, source_sheet_id and source_row. Original sheet row numbers provide direct traceability after stable sorting. All recognized rows are retained, including dates outside the reporting window; filtering applies only to report calculations.

Dates use YYYY-MM-DD, budget periods YYYY-MM. Amounts accept signed decimal numbers with valid optional thousands separators, and at most two fractional digits of monetary precision. Monetary output uses decimal arithmetic and two fractional digits. Count metrics require nonnegative integers and blank currency. Posted/pending/disputed and confirmed/unknown are explicit supported values. Unsupported metrics or values require clarification.

## Validation and provenance

Validate unique transaction IDs; unique (period, category, currency) budgets; and unique (date, source, metric) snapshots. Require one consistent business version for the ledger, one per budget period and one per revenue (date, source) population. Different dated revenue snapshot versions are expected and preserved.

Require ledger evidence on both specified dates. Normal mode requires Operations' completeness context for the entire period before publishing totals or comparisons. Explicit provisional mode can instead publish fetched-record arithmetic with unconfirmed coverage; its limits are below. Absence of an entire date population is not evidence of zero transactions in either mode. A valid budget source without current-month rows permits a partial draft: label missing budgets, withhold budget variances and ask Finance for the baselines. Missing individual budget mappings or snapshot comparators are explicit unresolved items. Earliest/latest observed dates alone do not establish completeness. Negative monetary baselines are preserved rather than treated as invalid numbers; their percentage/materiality rules remain unresolved while signed differences can be calculated.

Before publication, stdout prints one JSON SOURCE record per successfully read source: role, URL, spreadsheet ID, tab, sheet ID, fetch timestamp, source_versions, fetched_row_count and content SHA-256. The same identities, counts, timestamps, versions and hashes appear in the report. Versions come from source_version, not filename, fetch time or hashes.

## Operations completeness context

Obtain confirmation from the ledger's Operations source owner and record their evidence in a JSON file supplied through `--ledger-context`. This is supplementary validation evidence; all primary financial rows still come from fresh reads of the three Sheets on every run. No owner confirmation is bundled with the skill.

When that confirmation is unavailable, the user's instruction to proceed with available evidence permits an explicit `--allow-unconfirmed-ledger` invocation. It records `LEDGER_CONTEXT null` and a PROVISIONAL warning in stdout, and prominently marks the report's ledger coverage unconfirmed. Totals and comparisons describe fetched records only; all ledger materiality classifications are withheld. The required CSVs remain normalizations of fetched rows and must be read with the accompanying report. This exception does not meet interview-7's completeness prerequisite for confirmed ledger conclusions. Omitting both options still fails. Supplying malformed or mismatched context fails even with the provisional flag; the flag permits absent evidence, not evidence known to conflict.

The following is a format illustration with deliberately unusable placeholders. Replace each placeholder with independently supplied source-owner evidence, including the expected count. Do not copy the fetched count into this file and call it a confirmation.

```json
{
  "spreadsheet_id": "<owner-confirmed ledger spreadsheet ID>",
  "source_version": "<owner-confirmed business version>",
  "period_start": "2026-08-01",
  "period_end": "2026-08-11",
  "expected_transaction_count": null,
  "source_owner": "Operations",
  "confirmed_by": "<Operations confirmer>",
  "confirmed_at": "<ISO 8601 timestamp including timezone>",
  "context_reference": "<reference to the actual source-owner confirmation>"
}
```

For each manager request, the period must start at the earlier of that month's first day and the specified prior business date, and end on the reporting date. The expected count includes all statuses and amount states within that inclusive period. Rows outside it remain in normalized output but are excluded from this count. Spreadsheet ID and business version must exactly match the fresh ledger. Counts must be integers, not booleans; confirmation timestamps require a timezone and cannot be in the future. A missing, malformed, mismatched or unconfirmed context fails safely. Reconfirm with Operations when source version or scope changes.

The command prints verified LEDGER_CONTEXT before publication and includes the confirmer, timestamp, evidence reference, scope, version, spreadsheet identity and expected/observed period counts in the report. This records a human source-owner assertion and verifies its match with fetched evidence; it does not authenticate the human or independently prove business completeness from row count alone.

## Publication and recovery

The output directory lock serializes runs. At run start, atomically replace report.md with a STALE / FAILED marker before removing old CSVs. Attempt every CSV cleanup independently. If a CSV cannot be deleted, attempt to replace it atomically with an unmistakable unavailable marker, which intentionally does not satisfy the normalized CSV schema. If report marking fails, attempt to remove the old report. Any cleanup failure aborts publication and names the affected paths on stderr; a directory occupying a CSV path is left intact rather than recursively deleted. If filesystem permissions prevent every invalidation fallback, stderr explicitly declares the output directory unavailable; the operator must resolve those permissions before consuming outputs or rerunning.

Build new files in a temporary staging directory after sources validate, then replace CSVs and replace report.md last. Failure repeats independent cleanup without allowing a secondary cleanup exception to hide the original failure. A process killed during fetching leaves the initial marker; a process killed during publication may leave CSVs beside an unavailable report, which must not be consumed as current. Consumers must require the completed draft report and command success.

An overlapping invocation fails without altering the active run's outputs. Help is read-only. Invalid invocation arguments invalidate the selected outputs (or defaults if no output path can be parsed). The hidden .brief.lock is coordination state, not a cached source.

Access failures: confirm URLs remain viewable and the runtime permits HTTPS requests to docs.google.com and Google's export hosts. No authenticated fallback or old CSV substitution is performed. Layout failures: inspect the live workbook and clarify tab scope; add an explicit adapter only after the source owner defines it. Evidence failures: ask the responsible source owner to correct or clarify evidence, then rerun all three sources.

## Verification

Run from the skill root:

```bash
python3 -B -m unittest discover -s tests -v
```

Tests use small synthetic in-memory populations and synthetic owner confirmations to exercise financial rules, normal-mode completeness gating, explicit provisional coverage warnings, negative-baseline withholding and failure behavior. Production runs always fetch live Google sources; normal mode requires real Operations context, while provisional mode labels that evidence as absent. Python -B keeps bytecode caches out of the distributed skill. Verify a live rerun by comparing normalized CSV bytes and the report after excluding fetch timestamp lines. The results should match when live inputs, reporting dates and context or provisional mode remain unchanged.
