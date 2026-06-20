# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Added `PRIVACY.md` with guardrails for using real financial data locally.
- Added `contacts` support in the database for person-to-person classification context.
- Added `/contacts` management support for storing known payment contacts.
- Added local tooling scripts for anonymizing CSVs, validating real CSV imports, and inspecting dashboard results.
- Added dashboard confidence summaries and sanity warnings to make import quality easier to verify.

### Changed
- Improved BECU import profile handling for real Money Manager exports, including account filtering, alternate description columns, and multiple date formats.
- Improved amount sign detection using the export `Type` column when present.
- Improved LOC and Zelle classification behavior so ambiguous transactions stay in review unless the system has stronger context.
- Improved fallback handling for transfer and ignore rules so they no longer create unnecessary review work.
- Redesigned the import preview to focus on useful columns, clearer status badges, and better fit on smaller screens.
- Redesigned the dashboard to better separate current-window metrics from all imported data and latest import validation.
- Reworked the review queue into a filterable, card-based workflow so large review backlogs are manageable.

### Fixed
- Fixed parsing for BECU dates that use two-digit years.
- Fixed mixed-account CSV imports so rows are filtered to the selected account instead of being imported wholesale.
- Fixed a dashboard service indentation regression introduced during refactoring.
- Fixed review queue usability issues caused by rendering too many inline forms at once without filters.

### Tests
- Expanded import and dashboard test coverage for real BECU parsing, account filtering, LOC/Zelle handling, transfer fallback behavior, and sanity warnings.
