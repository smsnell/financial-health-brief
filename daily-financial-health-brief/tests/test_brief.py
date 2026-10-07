"""Behavioral tests; synthetic fixtures are never production input."""
import contextlib
import copy
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_brief.py"
SPEC = importlib.util.spec_from_file_location("brief", SCRIPT)
brief = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(brief)


def populations():
    def transaction(identity, day, amount, status="posted", state="confirmed", category="supplies"):
        return dict(zip(brief.SCHEMAS["transactions"], [identity, day, "operations", category, "synthetic", amount, "USD", status, "ledger", "ledger-v1", state]), source_row=identity[1:])
    ledger = [transaction("T2", "2026-08-10", "1,000.00"), transaction("T3", "2026-08-11", "800"),
              transaction("T4", "2026-08-11", "-50"), transaction("T5", "2026-08-11", "125", "pending"),
              transaction("T6", "2026-08-11", "25", "disputed"), transaction("T7", "2026-08-03", "", "pending", "unknown"),
              transaction("T8", "2026-07-31", "90", "pending")]
    budget = [dict(zip(brief.SCHEMAS["budget"], ["2026-08", "supplies", "2000", "USD", "operations", "review_material_overage", "budget", "budget-v1"]), source_row="2")]
    revenue = []
    for day in ["2026-08-10", "2026-08-11"]:
        for metric in sorted(brief.MONEY_METRICS | brief.COUNT_METRICS):
            revenue.append(dict(zip(brief.SCHEMAS["revenue"], [day, "tuition", metric, "1000" if metric in brief.MONEY_METRICS else "2", "USD" if metric in brief.MONEY_METRICS else "", "revenue-" + day]), source_row=str(len(revenue) + 2)))
    return {"transactions": ledger, "budget": budget, "revenue": revenue}


def metadata(sources):
    return [dict(role=role, url=f"https://docs.google.com/spreadsheets/d/{role}", spreadsheet_id=role, tab=role,
                 sheet_id="123", fetch_timestamp="2026-08-12T00:00:00+00:00", source_versions=sorted({r["source_version"] for r in rows}),
                 fetched_row_count=len(rows), content_sha256="synthetic", extra_columns=[]) for role, rows in sources.items()]


def ledger_context():
    """Independent synthetic source-owner assertion, never a production context."""
    return {"spreadsheet_id": "transactions", "source_version": "ledger-v1", "period_start": "2026-08-01", "period_end": "2026-08-11",
            "expected_transaction_count": 6, "source_owner": "Operations", "confirmed_by": "Synthetic Operations owner",
            "confirmed_at": "2026-08-12T00:00:00+00:00", "context_reference": "Synthetic owner confirmation for tests"}


def context_arg(tmp):
    path = Path(tmp) / "owner-context.json"
    path.write_text(json.dumps(ledger_context()))
    return ["--ledger-context", str(path)]


class FinancialBehavior(unittest.TestCase):
    def setUp(self):
        self.sources = populations()
        self.reporting = date(2026, 8, 11)
        self.prior = date(2026, 8, 10)

    def validate(self):
        brief.validate(self.sources, self.reporting, self.prior)

    def report(self):
        self.validate()
        return brief.render(self.sources, metadata(self.sources), self.reporting, self.prior, ledger_context())

    def test_signed_separate_totals_and_month_queue(self):
        report = self.report()
        for expected in ["Reporting-date posted total | +750.00 USD", "pending-confirmed total | +125.00 USD",
                         "disputed-confirmed total | +25.00 USD", "Prior-business-day posted total | +1000.00 USD",
                         "prior business day) | -250.00 USD", "supplies | +1750.00 USD"]:
            self.assertIn(expected, report)
        queue = report.split("## Unresolved transaction queue")[1].split("## Evidence gaps")[0]
        self.assertIn("T7 / 7", queue)
        self.assertNotIn("T8 / 8", queue)
        self.assertEqual(self.sources["transactions"][5]["amount"], "")

    def test_strict_materiality_boundaries(self):
        for actual, baseline, expected in [("5500", "5000", False), ("6600", "6000", False), ("6600.01", "6000", True), ("500", "0", False), ("500.01", "0", True)]:
            self.assertEqual(brief.variance(Decimal(actual), Decimal(baseline))[2], expected)
        self.assertIn("unavailable", brief.variance(Decimal("600"), Decimal("0"))[1])

    def test_negative_baseline_preserves_delta_and_withholds_undefined_rules(self):
        delta, percentage, material = brief.variance(Decimal("100"), Decimal("-10"))
        self.assertEqual(delta, Decimal("110"))
        self.assertIn("unavailable", percentage)
        self.assertIsNone(material)

    def test_negative_baselines_do_not_block_supported_figures(self):
        self.sources["transactions"][0]["amount"] = "-1000"
        self.sources["budget"][0]["budget_amount"] = "-2000"
        prior_revenue = next(r for r in self.sources["revenue"] if r["date"] == "2026-08-10" and r["metric"] == "collected_revenue")
        prior_revenue["value"] = "-1000"
        report = self.report()
        self.assertIn("Prior-business-day posted total | -1000.00 USD", report)
        self.assertIn("prior business day) | +1750.00 USD", report)
        self.assertIn("supplies | -250.00 USD | -2000.00 USD | +1750.00 USD | unavailable", report)
        self.assertIn("collected_revenue | +1000.00 USD | -1000.00 USD | +2000.00 USD | materiality unresolved", report)
        self.assertEqual(report.count("| Negative baseline rule unresolved |"), 3)

    def test_unknown_cannot_hide_a_value_or_be_posted(self):
        for field, value in [("amount", "0"), ("status", "posted")]:
            self.sources = populations()
            self.sources["transactions"][5][field] = value
            with self.assertRaises(brief.EvidenceError):
                self.validate()

    def test_duplicate_ids_and_budget_keys_rejected(self):
        for role in ["transactions", "budget", "revenue"]:
            self.sources = populations()
            self.sources[role].append(copy.deepcopy(self.sources[role][0]))
            with self.assertRaises(brief.EvidenceError):
                self.validate()

    def test_unmapped_category_is_visible(self):
        self.sources["transactions"][1]["category"] = "unmapped"
        self.assertIn("unmapped | +800.00 USD | unavailable", self.report())

    def test_missing_comparator_is_not_zero_filled(self):
        self.sources["revenue"] = [r for r in self.sources["revenue"] if not (r["date"] == "2026-08-10" and r["metric"] == "collected_revenue")]
        report = self.report()
        self.assertIn("collected_revenue | +1000.00 USD | unavailable | unavailable | unresolved", report)

    def test_count_currency_and_conflicting_versions_rejected(self):
        self.sources["revenue"][0]["source_version"] = "conflict"
        with self.assertRaises(brief.EvidenceError):
            self.validate()
        self.sources = populations()
        next(r for r in self.sources["revenue"] if r["metric"] in brief.COUNT_METRICS)["currency"] = "USD"
        with self.assertRaises(brief.EvidenceError):
            self.validate()

    def test_decimal_precision_and_numeric_format_validation(self):
        self.assertEqual(brief.monetary("1,200.50", "test"), Decimal("1200.50"))
        for value in ["12,00", "NaN", "Infinity", "1.001", "", "USD 500"]:
            with self.assertRaises(brief.EvidenceError):
                brief.monetary(value, "test")

    def test_missing_date_population_fails(self):
        self.sources["transactions"] = [r for r in self.sources["transactions"] if r["date"] != "2026-08-10"]
        with self.assertRaises(brief.EvidenceError):
            self.validate()

    def test_missing_current_month_budget_preserves_supported_daily_totals(self):
        self.sources["budget"][0]["period"] = "2026-07"
        report = self.report()
        self.assertIn("Reporting-date posted total | +750.00 USD", report)
        self.assertIn("supplies | +1750.00 USD | unavailable", report)
        self.assertIn("unmapped", report)

    def test_unconfirmed_population_cannot_render_a_financial_draft(self):
        self.validate()
        with self.assertRaises(brief.EvidenceError):
            brief.render(self.sources, metadata(self.sources), self.reporting, self.prior)

    def test_provisional_mode_labels_observed_totals_and_withholds_materiality(self):
        self.sources["budget"][0]["budget_amount"] = "0"
        self.sources["budget"].append(dict(self.sources["budget"][0], category="training", budget_amount="2000", source_row="3"))
        self.validate()
        report = brief.render(self.sources, metadata(self.sources), self.reporting, self.prior, allow_unconfirmed_ledger=True)
        self.assertIn("PROVISIONAL — LEDGER COMPLETENESS UNCONFIRMED", report)
        self.assertIn("Reporting-date posted total | +750.00 USD", report)
        self.assertIn("supplies | +1750.00 USD | +0.00 USD | +1750.00 USD | unavailable (zero baseline) | materiality unresolved", report)
        self.assertIn("training | +0.00 USD | +2000.00 USD | -2000.00 USD", report)
        self.assertIn("Zero observed rows do not establish zero spending", report)
        self.assertIn("| Ledger completeness unconfirmed |", report)
        self.assertNotIn("Expected / fetched period transactions", report)
        self.assertNotIn("month-to-date posted spend", report)

    def test_provisional_permission_does_not_override_conflicting_owner_context(self):
        context = ledger_context()
        context["expected_transaction_count"] = 999
        self.validate()
        with self.assertRaises(brief.EvidenceError):
            brief.render(self.sources, metadata(self.sources), self.reporting, self.prior, context, allow_unconfirmed_ledger=True)

    def test_removed_earlier_month_record_conflicts_with_owner_context(self):
        self.sources["transactions"] = [r for r in self.sources["transactions"] if r["date"] != "2026-08-03"]
        self.validate()  # Both daily comparison dates are still present.
        with self.assertRaises(brief.EvidenceError):
            brief.render(self.sources, metadata(self.sources), self.reporting, self.prior, ledger_context())

    def test_wrong_identity_version_scope_owner_and_count_are_rejected(self):
        self.validate()
        for field, value in [("spreadsheet_id", "other-ledger"), ("source_version", "old-version"), ("period_start", "2026-08-10"),
                             ("period_end", "2026-08-10"), ("source_owner", "Finance"), ("expected_transaction_count", 5),
                             ("expected_transaction_count", True), ("confirmed_at", "2099-01-01T00:00:00+00:00"),
                             ("confirmed_at", "2026-08-12T00:00:00"), ("confirmed_by", ""), ("context_reference", "")]:
            with self.subTest(field=field, value=value):
                context = ledger_context()
                context[field] = value
                with self.assertRaises(brief.EvidenceError):
                    brief.render(self.sources, metadata(self.sources), self.reporting, self.prior, context)

    def test_owner_confirmation_is_recorded_in_report(self):
        report = self.report()
        self.assertIn("Synthetic Operations owner", report)
        self.assertIn("Synthetic owner confirmation for tests", report)


class SourceAndPublicationBehavior(unittest.TestCase):
    def test_semantic_role_reordered_headers_and_extra_fields(self):
        row = populations()["budget"][0]
        fields = list(reversed(brief.SCHEMAS["budget"])) + ["business_note"]
        content = io.StringIO()
        writer = csv.writer(content)
        writer.writerow(fields)
        writer.writerow([row.get(field, "keep me") for field in fields])
        page = '<div id="9-grid-container"></div><div class="docs-sheet-tab-caption">Unrelated title</div>'
        role, rows, meta = brief.read_source("https://docs.google.com/spreadsheets/d/opaque", getter=lambda url: content.getvalue() if "export?" in url else page)
        self.assertEqual(role, "budget")
        self.assertEqual(rows[0]["business_note"], "keep me")
        self.assertEqual(meta["fetched_row_count"], 1)
        self.assertEqual(meta["sheet_id"], "9")

    def test_login_html_and_ambiguous_tabs_fail(self):
        for page in ["<html>Sign in</html>", '<div id="9-grid-container"></div><div id="10-grid-container"></div>']:
            with self.assertRaises(brief.EvidenceError):
                brief.read_source("https://docs.google.com/spreadsheets/d/opaque", getter=lambda url: page)

    def test_publication_preserves_all_rows_and_is_deterministic(self):
        sources = populations()
        sources["transactions"][0]["business_note"] = "retain this"
        brief.validate(sources, date(2026, 8, 11), date(2026, 8, 10))
        meta = metadata(sources)
        report = brief.render(sources, meta, date(2026, 8, 11), date(2026, 8, 10), ledger_context())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            brief.publish(output, sources, meta, report)
            before = {p.name: p.read_bytes() for p in (output / "normalized").glob("*.csv")}
            with (output / "normalized/transactions.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 7)
            self.assertEqual(next(r for r in rows if r["transaction_id"] == "T2")["business_note"], "retain this")
            for rows in sources.values():
                rows.reverse()
            brief.publish(output, sources, meta, report)
            self.assertEqual(before, {p.name: p.read_bytes() for p in (output / "normalized").glob("*.csv")})

    def test_failed_run_invalidates_previous_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "normalized").mkdir()
            for role in brief.SCHEMAS:
                (output / "normalized" / f"{role}.csv").write_text("old")
            (output / "report.md").write_text("old usable report")
            argv = ["--output-dir", tmp, "--report-date", "2026-08-11", "--prior-business-date", "2026-08-10"]
            for identity in ["a", "b", "c"]:
                argv.extend(["--source-url", f"https://docs.google.com/spreadsheets/d/{identity}"])
            with patch.object(brief, "read_source", side_effect=OSError("fetch failed")), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(brief.main(argv), 1)
            self.assertEqual(list((output / "normalized").glob("*.csv")), [])
            self.assertIn("STALE / FAILED", (output / "report.md").read_text())

    def test_invalid_invocation_invalidates_and_help_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "report.md").write_text("old")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(brief.main(["--output-dir", tmp]), 2)
            failed = (output / "report.md").read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(brief.main(["--output-dir", tmp, "--help"]), 0)
            self.assertEqual(failed, (output / "report.md").read_bytes())

    def test_cleanup_directory_error_marks_report_and_cleans_other_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "normalized").mkdir()
            (output / "normalized/budget.csv").mkdir()
            for role in ["transactions", "revenue"]:
                (output / "normalized" / f"{role}.csv").write_text("old usable CSV")
            (output / "report.md").write_text("old usable report")
            with patch.object(brief, "read_source") as reader, contextlib.redirect_stderr(io.StringIO()) as log:
                self.assertEqual(brief.main(["--output-dir", tmp]), 1)
                reader.assert_not_called()
            self.assertIn("STALE / FAILED", (output / "report.md").read_text())
            self.assertFalse((output / "normalized/transactions.csv").exists())
            self.assertFalse((output / "normalized/revenue.csv").exists())
            self.assertIn("budget.csv", log.getvalue())

    def test_delete_denied_csv_is_replaced_with_unavailable_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "normalized").mkdir()
            blocked = output / "normalized/budget.csv"
            blocked.write_text("old usable budget")
            (output / "normalized/revenue.csv").write_text("old usable revenue")
            (output / "report.md").write_text("old usable report")
            original = Path.unlink
            def unlink(path, *args, **kwargs):
                if path == blocked:
                    # The report must already be unavailable at the first cleanup attempt.
                    self.assertIn("STALE / FAILED", (output / "report.md").read_text())
                    raise PermissionError("synthetic delete denied")
                return original(path, *args, **kwargs)
            with patch.object(Path, "unlink", unlink), contextlib.redirect_stderr(io.StringIO()) as log:
                self.assertEqual(brief.main(["--output-dir", tmp]), 1)
            self.assertIn("STALE / FAILED", blocked.read_text())
            self.assertFalse((output / "normalized/revenue.csv").exists())
            self.assertIn("delete denied", log.getvalue())

    def test_marker_write_failure_removes_old_report_and_still_cleans_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "normalized").mkdir()
            (output / "normalized/revenue.csv").write_text("old usable revenue")
            (output / "report.md").write_text("old usable report")
            with patch.object(brief.os, "replace", side_effect=PermissionError("synthetic replace denied")), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(brief.main(["--output-dir", tmp]), 1)
            self.assertFalse((output / "report.md").exists())
            self.assertFalse((output / "normalized/revenue.csv").exists())

    def test_each_successful_rerun_reads_all_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--output-dir", tmp, "--report-date", "2026-08-11", "--prior-business-date", "2026-08-10"]
            argv += context_arg(tmp)
            for role in reversed(list(brief.SCHEMAS)):
                argv.extend(["--source-url", f"https://docs.google.com/spreadsheets/d/{role}"])
            def read(url):
                role = url.rsplit("/", 1)[1]
                sources = populations()
                return role, sources[role], next(m for m in metadata(sources) if m["role"] == role)
            with patch.object(brief, "read_source", side_effect=read) as reader, contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(brief.main(argv), 0)
                self.assertEqual(brief.main(argv), 0)
                self.assertEqual(reader.call_count, 6)
                self.assertEqual(log.getvalue().count("SOURCE {"), 6)
            self.assertIn("DRAFT", (Path(tmp) / "report.md").read_text())

    def test_partial_publication_failure_cleans_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--output-dir", tmp, "--report-date", "2026-08-11", "--prior-business-date", "2026-08-10"]
            argv += context_arg(tmp)
            for role in brief.SCHEMAS:
                argv.extend(["--source-url", f"https://docs.google.com/spreadsheets/d/{role}"])
            def read(url):
                role = url.rsplit("/", 1)[1]
                sources = populations()
                return role, sources[role], next(m for m in metadata(sources) if m["role"] == role)
            original = brief.os.replace
            attempted = []
            def replace(src, dst):
                attempted.append(Path(dst).name)
                if Path(dst).name == "budget.csv":
                    raise OSError("synthetic interrupted publication")
                original(src, dst)
            with patch.object(brief, "read_source", side_effect=read), patch.object(brief.os, "replace", side_effect=replace), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(brief.main(argv), 1)
            self.assertEqual(list((Path(tmp) / "normalized").glob("*.csv")), [])
            self.assertIn("STALE / FAILED", (Path(tmp) / "report.md").read_text())
            self.assertIn("budget.csv", attempted)

    def test_missing_confirmation_fails_after_all_live_sources_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "normalized").mkdir()
            for role in brief.SCHEMAS:
                (output / "normalized" / f"{role}.csv").write_text("old usable CSV")
            (output / "report.md").write_text("old usable report")
            argv = ["--output-dir", tmp, "--report-date", "2026-08-11", "--prior-business-date", "2026-08-10"]
            for role in brief.SCHEMAS:
                argv.extend(["--source-url", f"https://docs.google.com/spreadsheets/d/{role}"])
            def read(url):
                role = url.rsplit("/", 1)[1]
                sources = populations()
                return role, sources[role], next(m for m in metadata(sources) if m["role"] == role)
            with patch.object(brief, "read_source", side_effect=read) as reader, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as log:
                self.assertEqual(brief.main(argv), 1)
                self.assertEqual(reader.call_count, 3)
            self.assertEqual(list((output / "normalized").glob("*.csv")), [])
            self.assertIn("STALE / FAILED", (output / "report.md").read_text())
            self.assertIn("completeness", log.getvalue().lower())
            self.assertIn("completeness", (output / "report.md").read_text().lower())

    def test_provisional_end_to_end_reruns_freshly_read_and_still_invalidate_on_fetch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--output-dir", tmp, "--report-date", "2026-08-11", "--prior-business-date", "2026-08-10", "--allow-unconfirmed-ledger"]
            for role in brief.SCHEMAS:
                argv.extend(["--source-url", f"https://docs.google.com/spreadsheets/d/{role}"])
            def read(url):
                role = url.rsplit("/", 1)[1]
                sources = populations()
                return role, sources[role], next(m for m in metadata(sources) if m["role"] == role)
            with patch.object(brief, "read_source", side_effect=read) as reader, contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(brief.main(argv), 0)
                before = {p.name: p.read_bytes() for p in (Path(tmp) / "normalized").glob("*.csv")}
                self.assertEqual(brief.main(argv), 0)
                self.assertEqual(reader.call_count, 6)
                self.assertEqual(log.getvalue().count("SOURCE {"), 6)
                self.assertIn("PROVISIONAL DRAFT READY", log.getvalue())
                self.assertIn("LEDGER_CONTEXT null", log.getvalue())
            self.assertEqual(before, {p.name: p.read_bytes() for p in (Path(tmp) / "normalized").glob("*.csv")})
            self.assertIn("PROVISIONAL", (Path(tmp) / "report.md").read_text())
            with patch.object(brief, "read_source", side_effect=OSError("fetch failed")), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(brief.main(argv), 1)
            self.assertFalse(list((Path(tmp) / "normalized").glob("*.csv")))
            self.assertIn("STALE / FAILED", (Path(tmp) / "report.md").read_text())

    def test_provisional_flag_cannot_bypass_supplied_invalid_context_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.json"
            argv = ["--output-dir", tmp, "--report-date", "2026-08-11", "--prior-business-date", "2026-08-10",
                    "--allow-unconfirmed-ledger", "--ledger-context", str(path)]
            for role in brief.SCHEMAS:
                argv.extend(["--source-url", f"https://docs.google.com/spreadsheets/d/{role}"])
            def read(url):
                role = url.rsplit("/", 1)[1]
                sources = populations()
                return role, sources[role], next(m for m in metadata(sources) if m["role"] == role)
            conflict = ledger_context()
            conflict["source_version"] = "conflicting-version"
            for content in ["null", "{}", "not json", json.dumps(conflict)]:
                with self.subTest(content=content):
                    path.write_text(content)
                    with patch.object(brief, "read_source", side_effect=read) as reader, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(brief.main(argv), 1)
                        self.assertEqual(reader.call_count, 3)
                    self.assertIn("STALE / FAILED", (Path(tmp) / "report.md").read_text())
                    self.assertFalse(list((Path(tmp) / "normalized").glob("*.csv")))


if __name__ == "__main__":
    unittest.main()
