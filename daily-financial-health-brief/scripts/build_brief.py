#!/usr/bin/env python3
"""Fresh, read-only Google Sheets ingestion and draft financial reporting."""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "transactions": "transaction_id date account category description amount currency status source source_version amount_status".split(),
    "budget": "period category budget_amount currency owner review_rule source source_version".split(),
    "revenue": "date source metric value currency source_version".split(),
}
MONEY_METRICS = {"collected_revenue", "outstanding_balance", "payment_plan_balance"}
COUNT_METRICS = {"enrolled_students", "past_due_accounts"}


class EvidenceError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url):
    request = Request(url, headers={"User-Agent": "daily-financial-health-brief/1.0", "Cache-Control": "no-cache, no-store", "Pragma": "no-cache"})
    with urlopen(request, timeout=30) as response:
        host = urlparse(response.url).hostname or ""
        if not (host.endswith(".google.com") or host.endswith(".googleusercontent.com")):
            raise EvidenceError("Unexpected Google export destination")
        data = response.read(10_000_001)
        if len(data) > 10_000_000:
            raise EvidenceError("Source exceeds the 10 MB read limit; request a supported access route")
        return data.decode("utf-8-sig")


def number(value, context):
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value):
        raise EvidenceError(f"{context}: invalid numeric value {value!r}")
    try:
        result = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise EvidenceError(f"{context}: invalid amount") from exc
    if not result.is_finite():
        raise EvidenceError(f"{context}: non-finite amount")
    return result


def monetary(value, context):
    result = number(value, context)
    if result != result.quantize(Decimal("0.01")):
        raise EvidenceError(f"{context}: monetary precision exceeds cents; clarify with source owner")
    return result


def iso_date(value, context):
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceError(f"{context}: expected YYYY-MM-DD") from exc
    if result.isoformat() != value:
        raise EvidenceError(f"{context}: expected YYYY-MM-DD")
    return result


def read_source(url, getter=fetch):
    match = re.fullmatch(r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)(?:/[^\s]*)?", url)
    if not match:
        raise EvidenceError("Each source must be a Google Sheets HTTPS URL")
    identity = match.group(1)
    base = f"https://docs.google.com/spreadsheets/d/{identity}"
    page = getter(base + "/edit")
    gids = list(dict.fromkeys(re.findall(r'id="(\d+)-grid-container"', page)))
    captions = [html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
                for text in re.findall(r'<div[^>]*class="[^"]*docs-sheet-tab-caption[^"]*"[^>]*>(.*?)</div>', page, re.S)]
    if len(gids) != 1 or len(captions) != 1:
        raise EvidenceError(f"{base}: cannot unambiguously discover one tab; request clarification (multi-tab workbooks require an explicit adapter)")
    export = base + f"/export?format=csv&gid={gids[0]}"
    raw = getter(export)
    fetched_at = utc_now()
    table = list(csv.reader(io.StringIO(raw), strict=True))
    if not table:
        raise EvidenceError(f"{base}: empty source")
    fields = [s.strip().lower() for s in table[0]]
    if len(set(fields)) != len(fields) or any(not f for f in fields):
        raise EvidenceError(f"{base}: blank or duplicate headers")
    reserved = {"source_row", "source_tab", "source_sheet_id", "source_spreadsheet_id"}
    if reserved.intersection(fields):
        raise EvidenceError(f"{base}: source headers conflict with reserved traceability fields")
    roles = [role for role, required in SCHEMAS.items() if set(required).issubset(fields)]
    if len(roles) != 1:
        raise EvidenceError(f"{base}: fields do not identify exactly one source role")
    role = roles[0]
    rows = []
    for row_number, cells in enumerate(table[1:], 2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) > len(fields):
            raise EvidenceError(f"{base}, row {row_number}: too many cells")
        cells += [""] * (len(fields) - len(cells))
        row = dict(zip(fields, (cell.strip() for cell in cells)))
        row["source_row"] = str(row_number)
        rows.append(row)
    if not rows:
        raise EvidenceError(f"{base}: no recognized records")
    versions = sorted({row["source_version"] for row in rows})
    if "" in versions:
        raise EvidenceError(f"{base}: missing source_version")
    metadata = {"role": role, "url": base, "spreadsheet_id": identity, "tab": captions[0],
                "sheet_id": gids[0], "fetch_timestamp": fetched_at, "source_versions": versions,
                "fetched_row_count": len(rows), "content_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "extra_columns": [f for f in fields if f not in SCHEMAS[role]]}
    return role, rows, metadata


def validate(sources, reporting, prior):
    if set(sources) != set(SCHEMAS):
        raise EvidenceError("Exactly one ledger, budget and revenue source is required")
    if prior >= reporting:
        raise EvidenceError("Prior business date must precede reporting date")
    seen = set()
    for role, rows in sources.items():
        version_keys = defaultdict(set)
        for row in rows:
            context = f"{role} row {row['source_row']}"
            required = set(SCHEMAS[role]) - {"amount", "currency"}
            if any(not row[field] for field in required):
                raise EvidenceError(f"{context}: missing required evidence")
            if role != "revenue" or row["metric"] in MONEY_METRICS:
                if row["currency"] != "USD":
                    raise EvidenceError(f"{context}: expected USD; conversion is not authorized")
            if role == "transactions":
                key = row["transaction_id"]
                if key in seen:
                    raise EvidenceError(f"{context}: duplicate transaction ID {key}")
                seen.add(key)
                iso_date(row["date"], context)
                if row["status"] not in {"posted", "pending", "disputed"}:
                    raise EvidenceError(f"{context}: unsupported transaction status")
                if row["amount_status"] == "unknown":
                    if row["amount"] or row["status"] == "posted":
                        raise EvidenceError(f"{context}: unknown amounts must be blank and pending/disputed")
                elif row["amount_status"] == "confirmed":
                    row["amount"] = format(monetary(row["amount"], context), ".2f")
                else:
                    raise EvidenceError(f"{context}: unsupported amount_status")
                version_keys["ledger"].add(row["source_version"])
            elif role == "budget":
                if not re.fullmatch(r"\d{4}-\d{2}", row["period"]):
                    raise EvidenceError(f"{context}: expected YYYY-MM budget period")
                iso_date(row["period"] + "-01", context)
                key = (row["period"], row["category"], row["currency"])
                if key in seen:
                    raise EvidenceError(f"{context}: duplicate budget key {key}")
                seen.add(key)
                amount = monetary(row["budget_amount"], context)
                row["budget_amount"] = format(amount, ".2f")
                version_keys[row["period"]].add(row["source_version"])
            else:
                iso_date(row["date"], context)
                key = (row["date"], row["source"], row["metric"])
                if key in seen:
                    raise EvidenceError(f"{context}: duplicate revenue metric key {key}")
                seen.add(key)
                if row["metric"] in MONEY_METRICS:
                    row["value"] = format(monetary(row["value"], context), ".2f")
                elif row["metric"] in COUNT_METRICS:
                    value = number(row["value"], context)
                    if row["currency"] or value < 0 or value != value.to_integral_value():
                        raise EvidenceError(f"{context}: expected a nonnegative count with blank currency")
                    row["value"] = str(int(value))
                else:
                    raise EvidenceError(f"{context}: unknown metric meaning; clarify with Finance")
                version_keys[(row["date"], row["source"])].add(row["source_version"])
        if any(len(versions) != 1 for versions in version_keys.values()):
            raise EvidenceError(f"{role}: conflicting source versions within a population")
    for day in (reporting, prior):
        if not any(r["date"] == day.isoformat() for r in sources["transactions"]):
            raise EvidenceError(f"Ledger has no evidence for {day}; do not infer zero activity")


def money(value):
    return f"{value:+.2f} USD"


def verify_ledger_context(ledger, metadata, context, reporting, prior):
    """Match an Operations confirmation against freshly fetched business evidence."""
    if not isinstance(context, dict):
        raise EvidenceError("Ledger completeness is unconfirmed: supply --ledger-context with Operations' source-owner confirmation before preparing financial totals")
    text_fields = ["spreadsheet_id", "source_version", "period_start", "period_end", "source_owner", "confirmed_by", "confirmed_at", "context_reference"]
    if any(not isinstance(context.get(key), str) or not context[key].strip() for key in text_fields):
        raise EvidenceError("Ledger completeness context requires identity, version, scope, Operations owner, confirmer, timestamp and evidence reference")
    if context["source_owner"].strip().lower() != "operations":
        raise EvidenceError("Ledger completeness must be confirmed by the Operations source owner")
    meta = next(m for m in metadata if m["role"] == "transactions")
    if context["spreadsheet_id"] != meta["spreadsheet_id"]:
        raise EvidenceError("Ledger completeness context names a different spreadsheet")
    if {r["source_version"] for r in ledger} != {context["source_version"]}:
        raise EvidenceError("Ledger version conflicts with the source-owner completeness context; ask Operations to resolve it")
    scope_start = min(reporting.replace(day=1), prior)
    start = iso_date(context["period_start"], "ledger context period_start")
    end = iso_date(context["period_end"], "ledger context period_end")
    if start != scope_start or end != reporting:
        raise EvidenceError(f"Ledger completeness context must cover the entire requested period {scope_start} through {reporting}, including the prior business date")
    expected = context.get("expected_transaction_count")
    if type(expected) is not int or expected < 0:
        raise EvidenceError("Source-owner expected_transaction_count must be a nonnegative integer")
    observed = sum(start.isoformat() <= row["date"] <= end.isoformat() for row in ledger)
    if observed != expected:
        raise EvidenceError(f"Ledger population is incomplete or conflicting: Operations confirms {expected} transactions for the period, but the live ledger contains {observed}")
    try:
        confirmed_at = datetime.fromisoformat(context["confirmed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("Ledger confirmation timestamp must be ISO 8601 with a timezone") from exc
    if confirmed_at.tzinfo is None or confirmed_at > datetime.now(timezone.utc):
        raise EvidenceError("Ledger confirmation timestamp must include a timezone and cannot be in the future")
    confirmation = {key: context[key] for key in text_fields}
    confirmation.update(expected_transaction_count=expected, observed_transaction_count=observed)
    return confirmation


def variance(actual, baseline):
    delta = actual - baseline
    if baseline < 0:
        return delta, "unavailable (negative-baseline rule unresolved)", None
    material = abs(delta) > Decimal("500") and abs(delta) > baseline * Decimal("0.10")
    percent = "unavailable (zero baseline)" if baseline == 0 else f"{delta / baseline * 100:+.2f}%"
    return delta, percent, material


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def table(headers, rows):
    return ["| " + " | ".join(map(cell, headers)) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + ["| " + " | ".join(map(cell, row)) + " |" for row in rows]


def row_refs(rows):
    return ", ".join(f"{r['transaction_id']} (row {r['source_row']})" for r in rows) or "no observed rows"


def render(sources, metadata, reporting, prior, ledger_context=None, allow_unconfirmed_ledger=False):
    ledger = sources["transactions"]
    # An exception permits absent confirmation, never conflicting supplied evidence.
    confirmation = None if ledger_context is None and allow_unconfirmed_ledger else verify_ledger_context(ledger, metadata, ledger_context, reporting, prior)
    provisional = confirmation is None
    month_start = reporting.replace(day=1)
    mtd = [r for r in ledger if month_start.isoformat() <= r["date"] <= reporting.isoformat()]
    def selection(day, status):
        return [r for r in ledger if r["date"] == day.isoformat() and r["status"] == status and r["amount_status"] == "confirmed"]
    def total(rows):
        return sum((Decimal(r["amount"]) for r in rows), Decimal(0))
    posted = total(selection(reporting, "posted"))
    previous = total(selection(prior, "posted"))
    daily_delta, daily_pct, daily_material = variance(posted, previous)
    if provisional:
        daily_material = None
    lines = ["# Daily financial health brief", "", "**DRAFT — Operations Owner review and decisions required.**", "",
             f"Reporting date: **{reporting}** · Prior business date: **{prior}** · Budget period: **{reporting:%Y-%m}**", "",
             "Prepared for the operations meeting. Source systems were read only; this brief authorizes no spending, transfers or dispute resolution.", "",
             "## Evidence status", ""]
    if provisional:
        lines += ["**PROVISIONAL — LEDGER COMPLETENESS UNCONFIRMED.**", "",
                  "Operator selected --allow-unconfirmed-ledger under the user's instruction to proceed with available evidence. This explicitly departs from interview-7's requirement to confirm completeness before totals or comparisons. No Operations confirmation, expected population count or percentage rule has been invented.", "",
                  "All three source tabs were freshly fetched and their recognized records validated. Ledger totals and arithmetic comparisons below describe fetched records only; missing transactions could change them. They are not confirmed full-population financial conclusions. Ledger materiality classifications are withheld. Revenue snapshots retain their own source evidence. This provisional draft requires human review before reliance.", ""]
    else:
        lines += ["All discovered rows in each source tab were freshly fetched. Operations' completeness confirmation was matched against the live ledger's spreadsheet identity, business version and transaction count for the entire requested period. Fetch time establishes retrieval time; the source-owner context establishes the population being confirmed.", ""]
        lines += table(["Ledger completeness evidence", "Verified context"], [
        ["Operations confirmer", confirmation["confirmed_by"]], ["Confirmation timestamp", confirmation["confirmed_at"]],
        ["Evidence reference", confirmation["context_reference"]], ["Spreadsheet identity", confirmation["spreadsheet_id"]],
        ["Confirmed source version", confirmation["source_version"]],
        ["Inclusive period", f"{confirmation['period_start']} through {confirmation['period_end']}"],
        ["Expected / fetched period transactions", f"{confirmation['expected_transaction_count']} / {confirmation['observed_transaction_count']}"]])
    lines += ["", "## Daily activity", ""]
    if provisional:
        lines += ["Every figure in this table is an exact sum or difference of fetched records, with unconfirmed population coverage.", ""]
    daily_rows = []
    for label, day, status in [("Reporting-date posted total", reporting, "posted"), ("Reporting-date pending-confirmed total", reporting, "pending"), ("Reporting-date disputed-confirmed total", reporting, "disputed"), ("Prior-business-day posted total", prior, "posted")]:
        records = selection(day, status)
        daily_rows.append([label, money(total(records)), row_refs(records)])
    daily_rows.append(["Change in posted totals (reporting date minus prior business day)", money(daily_delta), "Reporting-date posted rows minus prior-business-day posted rows above"])
    lines += table(["Figure", "Exact signed amount", "Ledger evidence"], daily_rows)
    material_label = "unresolved / withheld" if daily_material is None else "yes" if daily_material else "no"
    lines += ["", f"Posted change: {daily_pct}; material: **{material_label}**. Pending and disputed amounts remain separate; unknown amounts are excluded.", "", "## Month-to-date posted spend versus monthly budget", "", "Actual is signed posted spending from month start through reporting date; variance is actual minus the full monthly budget, without prorating. A budget category with no posted rows is labeled no observed activity.", ""]
    if provisional:
        lines += ["MTD actuals, signed variances and percentages describe observed records only; they may change if transactions are missing. Zero observed rows do not establish zero spending. All ledger-based materiality decisions are withheld.", ""]
    actuals = defaultdict(list)
    for r in mtd:
        if r["status"] == "posted":
            actuals[r["category"]].append(r)
    budgets = {r["category"]: r for r in sources["budget"] if r["period"] == reporting.strftime("%Y-%m")}
    budget_rows, issues, findings = [], [], []
    if provisional:
        issues.append(["Ledger completeness unconfirmed", f"{min(month_start, prior)} through {reporting}; fetched population only", "Operations", "Obtain source-owner confirmation; all ledger materiality conclusions withheld. Provisional mode is an explicit exception to interview-7, not evidence of completeness"])
    if previous < 0:
        issues.append(["Negative baseline rule unresolved", "Daily posted comparison", "Operations", "Define percentage denominator and ten-percent test; percentage and materiality withheld"])
    if not budgets:
        issues.append(["Missing current-month budgets", reporting.strftime("%Y-%m"), "Finance", "Provide current monthly baselines; budget variances withheld while supported transaction totals remain available"])
    if daily_material:
        findings.append(f"Daily posted activity changed by {money(daily_delta)} ({daily_pct}) against {money(previous)}; see Daily activity row evidence.")
    for category in sorted(set(actuals) | set(budgets)):
        records = actuals[category]
        actual = total(records)
        if category not in budgets:
            budget_rows.append([category, money(actual), "unavailable", "unavailable", "unavailable", "unmapped", row_refs(records)])
            issues.append(["Unmapped category", category, "Operations + Finance", "Provide applicable monthly budget mapping; budget conclusion withheld"])
            continue
        b = budgets[category]
        baseline = Decimal(b["budget_amount"])
        delta, pct, material = variance(actual, baseline)
        if baseline < 0:
            issues.append(["Negative baseline rule unresolved", f"Budget category {category}", "Finance", "Define percentage denominator and ten-percent test; percentage and materiality withheld"])
        if provisional:
            material = None
        state = "materiality unresolved / withheld" if material is None else ("material " + ("overage" if delta > 0 else "under budget")) if material else "not material"
        if not records:
            state = "no observed activity; " + state
        evidence = f"{row_refs(records)}; budget row {b['source_row']} ({b['source_version']}); owner={b['owner']}; review_rule={b['review_rule']}"
        budget_rows.append([category, money(actual), money(baseline), money(delta), pct, state, evidence])
        if material:
            findings.append(f"{category}: month-to-date posted spend {money(actual)} versus monthly budget {money(baseline)}; variance {money(delta)} ({pct}). {'No observed posted activity; validate coverage with Operations.' if not records else 'See category row evidence.'}")
    lines += table(["Category", "MTD posted", "Monthly budget", "Signed variance", "Percentage", "Review status", "Evidence / context"], budget_rows)
    lines += ["", "## Revenue and balance snapshots", "", "Metrics are matched by source and metric across the two specified dates. Balances remain separate; count metrics are not subject to USD materiality thresholds.", ""]
    snapshots = {(r["date"], r["source"], r["metric"]): r for r in sources["revenue"]}
    metric_keys = sorted({(r["source"], r["metric"]) for r in sources["revenue"] if r["date"] in {reporting.isoformat(), prior.isoformat()}})
    for source in sorted({r["source"] for r in sources["revenue"]}):
        for metric in sorted(MONEY_METRICS):
            if (source, metric) not in metric_keys:
                metric_keys.append((source, metric))
    revenue_rows = []
    for source, metric in sorted(metric_keys):
        current = snapshots.get((reporting.isoformat(), source, metric))
        baseline = snapshots.get((prior.isoformat(), source, metric))
        monetary_metric = metric in MONEY_METRICS
        display = money if monetary_metric else lambda v: f"{v:+f}"
        evidence = "; ".join(f"{day}: row {r['source_row']} ({r['source_version']})" for day, r in [(reporting, current), (prior, baseline)] if r)
        if not current or not baseline:
            revenue_rows.append([source, metric, display(Decimal(current["value"])) if current else "unavailable", display(Decimal(baseline["value"])) if baseline else "unavailable", "unavailable", "unresolved", evidence])
            issues.append(["Missing snapshot/comparator", f"{source}/{metric}", "Finance", "Supply missing dated metric; comparison withheld, never zero-filled"])
            continue
        actual, base = Decimal(current["value"]), Decimal(baseline["value"])
        delta = actual - base
        state = "count metric"
        if monetary_metric:
            delta, pct, material = variance(actual, base)
            state = f"{'materiality unresolved / withheld' if material is None else 'material' if material else 'not material'}; {pct}"
            if base < 0:
                issues.append(["Negative baseline rule unresolved", f"{source}/{metric}", "Finance", "Define percentage denominator and ten-percent test; percentage and materiality withheld"])
            if material:
                findings.append(f"{source}/{metric}: change {money(delta)} ({pct}); {evidence}.")
        revenue_rows.append([source, metric, display(actual), display(base), display(delta), state, evidence])
    lines += table(["Source", "Metric", str(reporting), str(prior), "Signed change", "Review status", "Evidence"], revenue_rows)
    lines += ["", "## Supported material variances", ""]
    lines += ["- " + finding for finding in findings] or ["No material variance identified among comparisons with supported evidence and defined rules; withheld comparisons remain unresolved below."]
    queue = sorted([r for r in mtd if r["status"] in {"pending", "disputed"}], key=lambda r: (r["date"], r["transaction_id"]))
    lines += ["", "## Unresolved transaction queue", "", "All month-to-date pending/disputed rows are retained, including earlier dates. Operations owns ledger clarification; the Operations Owner decides resolution.", ""]
    lines += table(["ID / row", "Date", "Category", "Status", "Amount state", "Signed amount", "Description"], [[f"{r['transaction_id']} / {r['source_row']}", r["date"], r["category"], r["status"], r["amount_status"], money(Decimal(r["amount"])) if r["amount"] else "unknown — excluded", r["description"]] for r in queue])
    lines += ["", "## Evidence gaps and handoff", ""]
    for r in queue:
        if r["amount_status"] == "unknown":
            issues.append(["Unknown amount", f"{r['transaction_id']} / ledger row {r['source_row']}", "Operations", "Clarify amount; record retained outside all numeric totals"])
    lines += table(["Issue", "Evidence", "Responsible source owner", "Requested clarification"], issues)
    lines += ["", "The Operations Owner reviews this draft and makes spending, escalation and dispute decisions. Missing evidence cannot support a conclusion. Budget review_rule values provide additional review context without replacing the materiality test.", "", "## Source provenance", ""]
    for m in sorted(metadata, key=lambda m: m["role"]):
        dates = sorted({r.get("date", r.get("period")) for r in sources[m["role"]]})
        lines += [f"### {m['role']}", "", f"- Source URL: {m['url']}", f"- Spreadsheet identity: `{m['spreadsheet_id']}`", f"- Tab: {m['tab']} · sheet ID: `{m['sheet_id']}`", f"- Fetch timestamp (UTC): {m['fetch_timestamp']}", f"- Source versions: {', '.join(m['source_versions'])}", f"- Fetched data rows (header/blank rows excluded): {m['fetched_row_count']}", f"- Observed date/period coverage: {dates[0]} through {dates[-1]}", f"- Fetched content SHA-256 (integrity evidence, not a business version): `{m['content_sha256']}`", ""]
    lines += ["## Calculation notes", "", "Exact monetary calculations use decimal arithmetic; signs are preserved. Percentages alone are rounded to two decimals. For supported comparisons with positive baselines, materiality is abs(variance) > 0.10 × baseline AND abs(variance) > 500; equality does not qualify. A zero baseline has no percentage ratio and uses only the strict USD 500 test. For negative baselines, signed differences remain available, while percentage and materiality are withheld because the interview supplies no negative-baseline percentage formula. In provisional mode, all ledger materiality conclusions are withheld regardless of baseline. Normalized outputs retain every recognized row and extra source fields, with spreadsheet/tab/row traceability. Stable inputs, completeness context or provisional mode, and dates produce stable calculations and row order; fetch timestamps and hashes describe each live retrieval.", ""]
    return "\n".join(lines)


def write_failure_marker(path, content):
    """Replace a local artifact atomically, without following its symlink target."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".brief-failed-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def invalidate(output, message):
    """Mark the report first; attempt every CSV independently and return errors."""
    errors = []
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [f"Cannot access output directory {output}: {exc}"]
    content = f"# FINANCIAL BRIEF UNAVAILABLE\n\n**STALE / FAILED — no current usable deliverables.**\n\n{message}\n\nUTC: {utc_now()}\n"
    report = output / "report.md"
    try:
        write_failure_marker(report, content)
    except OSError as exc:
        errors.append(f"Cannot mark {report} unavailable: {exc}")
        try:
            report.unlink(missing_ok=True)
        except OSError as remove_exc:
            errors.append(f"Cannot remove old report {report}: {remove_exc}")
    for role in SCHEMAS:
        path = output / "normalized" / f"{role}.csv"
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"Cannot remove {path}: {exc}")
            # A denied deletion must not leave a readable old CSV as current.
            try:
                write_failure_marker(path, content)
            except OSError as mark_exc:
                errors.append(f"Cannot mark {path} unavailable: {mark_exc}")
    return errors


def fail_run(output, reason):
    errors = invalidate(output, f"Run failed: {reason}\n\nResolve the reported output or source-evidence errors before rerunning.")
    print(f"FAILED: {reason}", file=sys.stderr)
    for error in errors:
        print(f"INVALIDATION ERROR: {error}", file=sys.stderr)
    if errors:
        print("Output cleanup failed; publication stopped. Treat this output directory as unavailable until the reported filesystem problems are resolved.", file=sys.stderr)
    return 1


def publish(output, sources, metadata, report):
    with tempfile.TemporaryDirectory(prefix=".brief-", dir=output) as tmp:
        stage = Path(tmp)
        for role in SCHEMAS:
            extra = sorted({field for row in sources[role] for field in row} - set(SCHEMAS[role]) - {"source_row"})
            fields = SCHEMAS[role] + extra + ["source_spreadsheet_id", "source_tab", "source_sheet_id", "source_row"]
            m = next(m for m in metadata if m["role"] == role)
            rows = sources[role]
            sort_keys = {"transactions": ("date", "transaction_id"), "budget": ("period", "category"), "revenue": ("date", "source", "metric")}[role]
            with (stage / f"{role}.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for row in sorted(rows, key=lambda r: tuple(r[k] for k in sort_keys)):
                    writer.writerow({**row, "source_spreadsheet_id": m["spreadsheet_id"], "source_tab": m["tab"], "source_sheet_id": m["sheet_id"]})
        (stage / "report.md").write_text(report, encoding="utf-8")
        (output / "normalized").mkdir(exist_ok=True)
        for role in SCHEMAS:
            os.replace(stage / f"{role}.csv", output / "normalized" / f"{role}.csv")
        os.replace(stage / "report.md", output / "report.md")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", action="append", required=True, help="Repeat for all three Google Sheets; order does not matter")
    parser.add_argument("--report-date", required=True, help="Manager-specified YYYY-MM-DD")
    parser.add_argument("--prior-business-date", required=True, help="Manager-specified YYYY-MM-DD; no calendar inference")
    parser.add_argument("--output-dir", default="../deliverables", help="Relative to skill root (default: ../deliverables)")
    parser.add_argument("--ledger-context", help="Operations-confirmed completeness JSON; path relative to skill root or absolute")
    parser.add_argument("--allow-unconfirmed-ledger", action="store_true", help="Explicitly permit a provisional fetched-record draft without owner confirmation; ledger materiality withheld. Conflicting supplied context still fails")
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        parser.print_help()
        return 0
    output_parser = argparse.ArgumentParser(add_help=False)
    output_parser.add_argument("--output-dir", default="../deliverables")
    try:
        output_args, _ = output_parser.parse_known_args(argv)
        output = (ROOT / output_args.output_dir).resolve()
    except SystemExit:
        # Acquire the normal output lock before invalidating an invalid invocation.
        output = (ROOT / "../deliverables").resolve()
    started = time.monotonic()
    # Linux/WSL operator environment: prevent interleaved publications by concurrent runs.
    import fcntl
    try:
        output.mkdir(parents=True, exist_ok=True)
        lock = (output / ".brief.lock").open("a")
    except OSError as exc:
        return fail_run(output, exc)
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("FAILED: another run owns this output directory", file=sys.stderr)
            return 1
        except OSError as exc:
            return fail_run(output, exc)
        try:
            errors = invalidate(output, "Run started; outputs remain unavailable until fresh evidence validates.")
            if errors:
                raise EvidenceError("Output cleanup failed: " + "; ".join(errors))
            try:
                args = parser.parse_args(argv)
            except SystemExit:
                errors = invalidate(output, "Invalid invocation; no current usable deliverables.")
                if errors:
                    return fail_run(output, "; ".join(errors))
                return 2
            reporting = iso_date(args.report_date, "report date")
            prior = iso_date(args.prior_business_date, "prior business date")
            if len(args.source_url) != 3 or len(set(args.source_url)) != 3:
                raise EvidenceError("Provide exactly three distinct source URLs")
            sources, metadata = {}, []
            for url in args.source_url:
                role, rows, meta = read_source(url)
                print("SOURCE " + json.dumps(meta, sort_keys=True), flush=True)
                if role in sources:
                    raise EvidenceError(f"Duplicate source role: {role}")
                sources[role] = rows
                metadata.append(meta)
            if len({m["spreadsheet_id"] for m in metadata}) != 3:
                raise EvidenceError("Provide three distinct spreadsheet identities")
            validate(sources, reporting, prior)
            context = json.loads((ROOT / args.ledger_context).read_text(encoding="utf-8")) if args.ledger_context else None
            confirmation = None if not args.ledger_context and args.allow_unconfirmed_ledger else verify_ledger_context(sources["transactions"], metadata, context, reporting, prior)
            print("LEDGER_CONTEXT " + json.dumps(confirmation, sort_keys=True), flush=True)
            if confirmation is None:
                print("PROVISIONAL: ledger completeness unconfirmed; totals cover fetched records only and ledger materiality is withheld", flush=True)
            report = render(sources, metadata, reporting, prior, confirmation, args.allow_unconfirmed_ledger)
            publish(output, sources, metadata, report)
            print(f"{'PROVISIONAL DRAFT READY' if confirmation is None else 'DRAFT READY'}: {output / 'report.md'} ({time.monotonic() - started:.2f}s)")
            return 0
        except (Exception, KeyboardInterrupt) as exc:
            return fail_run(output, exc)


if __name__ == "__main__":
    raise SystemExit(main())
