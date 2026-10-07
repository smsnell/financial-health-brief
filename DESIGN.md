## Scenario

Quillhaven Academy's Finance and Operations Manager needs a reliable daily financial brief. Preparing it from separate records takes time and can leave uncertainty hidden in a polished report.

## Your task

Build an Agent Skills-compliant skill named `daily-financial-health-brief` that another operator can run to produce the manager's requested brief from current business sources. Keep the work read-only and the brief a draft for human review; do not edit a source system or perform a financial action.

## Deliverables

**Interview records — `interviews/*.md`.** Include the original Work Sim Markdown export for every interview session, with its session metadata and complete participant-visible messages. Keep one final complete export per session without rewriting or summarizing it. Commit and push these files in the submitted code revision and ensure the facilitator can read them. Coding-session capture remains a separate requirement. If the export is unavailable, contact the facilitator; do not manufacture a replacement.

Include these paths in your repository:

- `daily-financial-health-brief/SKILL.md` with valid `name` and `description` frontmatter;
- an executable implementation under `daily-financial-health-brief/scripts/`;
- focused operating knowledge under `daily-financial-health-brief/references/`;
- `deliverables/normalized/transactions.csv`;
- `deliverables/normalized/budget.csv`;
- `deliverables/normalized/revenue.csv`; and
- `deliverables/report.md`: the manager's requested brief, with traceable findings, source metadata and unresolved items.

Required CSV columns:

- `transactions.csv`: `transaction_id`, `date`, `account`, `category`, `description`, `amount`, `currency`, `status`, `source`, `source_version`, `amount_status`;
- `budget.csv`: `period`, `category`, `budget_amount`, `currency`, `owner`, `review_rule`, `source`, `source_version`; and
- `revenue.csv`: `date`, `source`, `metric`, `value`, `currency`, `source_version`.

Preserve every recognized source row. Extra source columns do not have to appear in normalized output unless they carry business meaning needed for traceability or review.

Required `report.md` figures. Report each of these as an exact number carrying its own label and its sign, not as a rounded figure or as a description of the direction of travel: the reporting date's posted total, its pending-confirmed total and its disputed-confirmed total; the prior business day's posted total; and the change between those two posted totals. The interview establishes what each figure means, which rows it draws on and how it is derived.

Document one programmatic end-to-end command, its runtime and dependencies. Use relative paths from the skill root, validate inputs before producing usable outputs, support deterministic reruns, and avoid manual per-row processing or hard-coded expected answers. Identify source roles from field meaning, not filenames or column positions.

Accept the three interview-disclosed Google Sheets URLs as runtime inputs. Every run must freshly read all three through their view-only access. Bundled, manually downloaded or previously cached CSVs cannot be the primary input. Before publishing outputs, print each source URL or spreadsheet identity, sheet/tab identity, fetch timestamp, source version and fetched row count for the Entire transcript, and record the same metadata in `report.md`. If a source cannot be fetched or validated, fail safely without silently reusing an older copy. A failed run must also not leave an earlier run's deliverables at the required output paths where they can be read as current: remove, invalidate or unmistakably mark them as stale or failed, because not overwriting them is not enough. Request clarification for incomplete or ambiguous evidence; do not invent values.
