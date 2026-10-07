# Financial interpretation and handoff

Authority: DESIGN.md and interviews/interview-7.md, plus the user's subsequent instruction to make do with available information. That instruction authorizes a clearly identified provisional exception, not an assertion that the interview's completeness prerequisite has been satisfied. The initial request is August 11, 2026 versus August 10 for the August 12 operations meeting; current monthly targets are August 2026. Future runs take manager-specified dates.

## Status and amount

Daily figures include only the date named in their label. Sum signed confirmed amounts separately for posted, pending and disputed rows; never combine them into a cash total. Reporting-date posted minus prior-business-date posted is the daily change. Preserve negative posted credits/corrections and genuine numeric zeros.

Transaction status and amount state are distinct. An explicitly unknown amount is blank, retained and excluded from totals; only pending/disputed transactions may have this state. A posted amount must be confirmed. Keep all pending/disputed rows from month start through reporting date in the unresolved queue, including unknown amounts and earlier dates.

## Budget reconciliation

For every category, actual is the sum of signed posted ledger amounts from month start through reporting date. Match the applicable budget by period, category and USD currency. Variance = actual minus numeric full monthly target; do not prorate. Display all current budget categories, including no observed posted activity, and all posted categories, including unmapped categories. An absent budget is unavailable, never an invented zero. Preserve owner and review_rule; review_rule adds context and does not override materiality.

## Snapshots and materiality

Match revenue snapshots by source and metric for the reporting date and specified prior business date. Compare collected_revenue, outstanding_balance and payment_plan_balance separately. Preserve enrolled_students and past_due_accounts as nonmonetary counts; no USD threshold applies to those counts. Never sum payment-plan and outstanding balances or infer a ledger/snapshot accounting identity that the manager has not supplied.

For a known nonnegative baseline, signed variance = actual minus baseline. Materiality requires both abs(variance) > 10% × baseline and abs(variance) > USD 500. Equality at either threshold is not material. Preserve an exact signed monetary variance for zero baselines; percentage is unavailable, and only abs(variance) > USD 500 qualifies. Round displayed percentages only; do not round monetary calculations or threshold decisions.

Interview-7 repeats that materiality applies regardless of baseline sign, but its new answer about a negative percentage describes only zero baselines. It still does not specify the negative-baseline percentage denominator or whether ten percent uses the signed value or magnitude. The executable preserves the signed difference, labels the percentage unavailable and materiality unresolved, and records a review item for the responsible owner. It does not silently apply abs(baseline). Supported sections continue. Negative transaction credits still participate in daily and month-to-date totals. All monetary sources and thresholds must be USD; foreign exchange conversion is outside this workflow.

## Missing evidence and responsibilities

Unmapped posted categories are labeled and escalated; missing revenue comparators remain unresolved and never zero-filled. Interview-7 retains the explicit permission for a draft when current-month budget evidence is missing: preserve independently supported transaction totals and open items, withhold unsupported budget variances and ask Finance to supply the baselines. Even if the valid budget source contains no current-month rows, supported sections remain available with explicit gaps. Ledger conclusions require confirmed completeness; the provisional exception below instead presents observed-record arithmetic. Invalid/ambiguous amounts, conflicting versions, duplicates and unavailable or invalid entire source populations prevent usable output in every mode.

Operations owns ledger clarification. Finance owns budget and revenue clarification. Budget row owners provide category context; they do not replace source ownership. The Operations Owner reviews the draft and decides spending, escalation and dispute resolution. The command documents clarification requests; it does not send messages or take decisions.

Interview-7 explicitly requires confirmation of the complete ledger population before totals or comparisons. Verify records and version against the source context for the entire requested period; clarify missing or conflicting evidence with Operations before proceeding. A fresh full-tab fetch alone verifies retrieval coverage, not business completeness.

The implementation records Operations' confirmation as a runtime JSON context and compares its independently confirmed transaction count, business version, spreadsheet identity and exact inclusive period with the live ledger. The period begins at the earlier of month start and prior business date and ends on reporting date. In normal mode, missing confirmation or any mismatch stops publication and invalidates prior outputs. This JSON format is an implementation choice for recording the interview's required source context; it is not a new business rule or an automatic certification. Do not generate an owner confirmation from observed rows, default an expected count to the fetched count, or treat the interview's description of the process as confirmation of a particular ledger population.

The user's instruction to proceed for now is implemented through `--allow-unconfirmed-ledger`. If no context is supplied, this explicit mode produces a PROVISIONAL draft identifying coverage as unconfirmed. The five required daily figures, MTD observed amounts and arithmetic differences describe only the freshly fetched records; missing transactions could change them. All ledger-based materiality decisions are withheld. Percentages with defined baselines are arithmetic over observed records, not confirmed financial conclusions. No observed rows means zero observed spending only, never proven zero activity. Revenue comparisons can proceed from their separately validated snapshot evidence. The report records the exception, review limitations and outstanding Operations item. A context supplied alongside this flag must still validate; incomplete, conflicting or malformed supplied evidence cannot be overridden.

With confirmed completeness, a budget category with no observed posted transactions may be shown as zero observed spending and labeled no observed activity. Do not claim a financial trend or forecast solely from a daily change or month-to-date underspend against a full monthly target.
