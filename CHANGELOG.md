# Changelog

Daily running journal of work completed on MoneyView.

## 2026-06-19

### Stuff Done
- Bootstrapped MoneyView as a local-first finance CSV workflow using Flask, SQLite, and pytest.
- Added the initial database schema for accounts, import profiles, imports, canonical transactions, categories, rules, balance snapshots, recurring bills, and user settings.
- Built the profile-driven CSV normalization pipeline with canonical transaction shaping and stable transaction-hash deduplication.
- Added seeded defaults for accounts, categories, settings, starter rules, and reusable import profiles including BECU and generic CSV options.
- Built the categorization rules engine with priority ordering and matched-rule metadata for explainability.
- Added import preview flow with parser diagnostics, predicted category/class output, review flags, and duplicate-awareness.
- Added the review queue workflow for recategorizing transactions, reclassifying them, and creating follow-up rules from reviewed rows.
- Built the first dashboard with pay-period and month windows, class-aware totals, data-confidence metrics, and safe-to-spend support.
- Added supporting services for pay-period calculation and safe-to-spend math.
- Added architecture docs for the generic CSV importer, import profiles, and rules engine.
- Added automated test coverage for import mapping, duplicate behavior, dashboard integrity, pay-period filtering, and class-based exclusions.
- Added the initial fixture data and repo ignore rules for Python/cache/build artifacts.

## 2026-06-20

### Stuff Done
- Got the GitHub repo going: https://github.com/chrisjmendoza/MoneyView
- Added the first project README with setup, run, test, import, and privacy instructions.
- Added `PRIVACY.md` with guardrails for using real financial data locally.
- Added `contacts` support in the database for person-to-person classification context.
- Added `/contacts` management support for storing known payment contacts.
- Added local scripts for anonymizing CSVs, validating real CSV imports, and inspecting dashboard results.
- Added dashboard confidence summaries and sanity warnings to make import quality easier to verify.
- Improved BECU import profile handling for real Money Manager exports, including account filtering, alternate description columns, and multiple date formats.
- Improved amount sign detection using the export `Type` column when present.
- Improved LOC and Zelle classification behavior so ambiguous transactions stay in review unless the system has stronger context.
- Improved fallback handling for transfer and ignore rules so they no longer create unnecessary review work.
- Redesigned the import preview to focus on useful columns, clearer status badges, and better fit on smaller screens.
- Redesigned the dashboard to better separate current-window metrics from all imported data and latest import validation.
- Reworked the review queue into a filterable, card-based workflow so large review backlogs are manageable.
- Fixed parsing for BECU dates that use two-digit years.
- Fixed mixed-account CSV imports so rows are filtered to the selected account instead of being imported wholesale.
- Fixed a dashboard service indentation regression introduced during refactoring.
- Fixed review queue usability issues caused by rendering too many inline forms at once without filters.
- Expanded import and dashboard test coverage for real BECU parsing, account filtering, LOC/Zelle handling, transfer fallback behavior, and sanity warnings.
