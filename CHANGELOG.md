# Changelog

Daily running journal of work completed on MoneyView.

## 2026-06-20 (session 4)

### Stuff Done
- Added CSRF protection to all POST forms. A random 32-byte token is generated into the Flask session on first page load, exposed as a `<meta name="csrf-token">` tag, and injected into every POST form automatically via a one-time JS pass at page load — no template edits required. All POST requests are rejected with 403 if the token is missing or wrong. CSRF is bypassed in the test environment (`app.testing`).
- Added `/budgets` — a monthly budget-vs-actual page. Each active category with spending or a saved budget appears with its current-month actual spend, an editable budget field, and a visual progress bar. Over-budget rows are highlighted in amber. Budgets are stored in a new `category_budgets` table (FK to categories, CASCADE delete). Added Budgets to the site nav.
- Added annual spending projection to the dashboard. `compute_annual_projection()` averages the last 3 months of net expense and multiplies by 12. Displayed as a card above the 3-month trend table.
- Added per-category spending sparklines to the dashboard top-10 categories table. `spending_trend_by_category_month()` returns monthly spend per category for the last 3 months; the template renders 3 proportionally-sized bars as inline SVG-free HTML using CSS custom properties for height (same approach as the confidence meter).
- Fixed VS Code Problems tab: replaced the only Jinja2 expression inside a `<script>` block (`{{ restored_scroll_y or 'null' }}`) with a `data-scroll-y` attribute on the section element, read in JS via `.dataset.scrollY`.
- Rewrote the review queue with merchant grouping and collapsible cards. Transactions with the same merchant are automatically grouped into a single card showing the total and a mini transaction list; one "Categorize all N" bulk form applies category, class, note, and an optional rule to the entire group. "Ungroup" reveals individual collapsible cards for each transaction in the group (useful for PayPal or mixed-purpose merchants). "Back to group view" re-groups them. All individual cards (both standalone and within groups) use `<details>/<summary>` for collapse — the summary line shows date, amount, merchant/description, and badges; the full decision form is revealed on click.

## 2026-06-20 (session 3)

### Stuff Done
- Built `/imports` — import history page listing every past CSV import with account, profile, file name, row counts, and a Rollback button. Rollback deletes all transactions sourced from that import (via `source_import_id` FK) then removes the import record in one atomic transaction. Added Imports to the site nav.
- Fixed bill frequency calculation in `compute_bills_due_before_next_paycheck` to support weekly and annual bills. Weekly bills count `(days_until_payday // 7)` occurrences per period. Annual bills require a `due_month` (1–12) in addition to `due_day`; the column is added via `ensure_integrity_columns` migration. Both the "Add bill" and "Edit bill" forms now include a Due Month selector, visible for all frequencies and required for annual.
- Made payroll description detection configurable: replaced the hardcoded `SOUND PROP` string in `build_sanity_warnings` with a `payroll_description_hint` user setting. Added field to the dashboard Pay Settings form, seeded empty default, and wired through `build_dashboard` and `save_settings`.
- Fixed `top_categories` SQL query to net out refunds: changed from `amount < 0 AND class = 'expense'` to `class IN ('expense', 'refund')` with a CASE expression so positive refund amounts reduce the category total. Categories with zero or negative net spend are excluded via `HAVING total_spend > 0`.
- Removed the unused `FOOD_CATEGORIES = (...)` Python constant from `dashboard_service.py` (the SQL always referenced the names directly; the constant was dead code).
- Added `/transactions/export` — downloads all transactions matching the current filter state as a CSV file named `moneyview-export-YYYY-MM-DD.csv`. Added an Export CSV button to the transactions page filter bar.
- Added input validation to `/settings` POST: validates `payday_anchor` as a real ISO date and validates decimal fields (`normal_paycheck_amount`, `checking_floor`, `manual_bills_due_before_next_paycheck`) before touching the DB. Returns a flash error on invalid input.
- Added net worth to the dashboard: `compute_net_worth()` sums checking/savings/cash balances and subtracts credit card/line of credit/loan balances from the latest snapshot per account. Displayed as a hero card between the view-window cards and the sanity checks section.
- Added 3-month spending trend to the dashboard: `spending_trend_by_month()` returns monthly gross expense, refund, and net spend for the last 3 calendar months using SQLite's `strftime`. Shown as a compact table before the balance/settings section.
- Set `MAX_CONTENT_LENGTH = 10 MB` on the Flask app to cap CSV upload size. Added a 413 error handler that flashes a descriptive error and redirects back to the import page.

## 2026-06-20

### Stuff Done
- Conducted a multi-perspective codebase analysis (user, developer, engineer, financial expert) covering correctness, UX gaps, security, and financial modeling accuracy.
- Created `TODO.md` as a prioritized improvement backlog organized into five tiers.
- Added `PRAGMA journal_mode = WAL` to the database connection so concurrent reads no longer block during development.
- Replaced Python `hash()`-based IDs for bills, contacts, and balance snapshots with `uuid4()` — hash-based IDs are not stable across Python runs and have collision risk.
- Moved `SECRET_KEY` out of source code. On first run the app auto-generates a random 32-byte key and persists it to `data/.secret_key` (gitignored); subsequent runs reuse it silently. The `SECRET_KEY` environment variable overrides the file for networked deployments. Eliminates the startup warning while ensuring sessions are stable across restarts.
- Fixed the categorization rule upsert from `INSERT OR REPLACE` to `INSERT ... ON CONFLICT DO UPDATE SET`, which preserves `created_at` (REPLACE deletes then inserts, silently dropping the timestamp).
- Added flash messages to all form POST handlers (balance, settings, bill, contact, update_review) and a flash message display block to the base template so users get feedback after every save.
- Built `/rules` — a rules management page that lists all categorization rules with their priority, pattern, match type, category, and class. Each rule has an inline edit form, an enable/disable toggle, and a delete button with confirmation.
- Built `/transactions` — a transaction browser for viewing and re-classifying any imported transaction, not just ones flagged for review. Supports filtering by account, class, category, description search, and date range, with pagination and an inline edit form on each row including a "keep in review queue" checkbox.
- Built `/bills` — a dedicated recurring bills management page with a create form, inline edit form per bill, delete confirmation, and active/inactive toggle. Bills are used by the safe-to-spend calculation.
- Added Rules, Transactions, and Bills to the site nav in `base.html`.
- Updated README with the new pages table, configuration section, current status summary, and revised roadmap.
- Got the GitHub repo going: https://github.com/chrisjmendoza/MoneyView
- Added the first project README with setup, run, test, import, and privacy instructions.
- Expanded the README with a roadmap and development notes so the GitHub repo has clearer project direction.
- Added `PRIVACY.md` with guardrails for using real financial data locally.
- Added `contacts` support in the database for person-to-person classification context.
- Added `/contacts` management support for storing known payment contacts.
- Added local scripts for anonymizing CSVs, validating real CSV imports, and inspecting dashboard results.
- Added dashboard confidence summaries and sanity warnings to make import quality easier to verify.
- Improved BECU import profile handling for real Money Manager exports, including account filtering, alternate description columns, and multiple date formats.
- Improved amount sign detection using the export `Type` column when present.
- Improved line-of-credit and Zelle classification behavior so ambiguous transactions stay in review unless the system has stronger context.
- Improved fallback handling for transfer and ignore rules so they no longer create unnecessary review work.
- Redesigned the import preview to focus on useful columns, clearer status badges, and better fit on smaller screens.
- Redesigned the dashboard to better separate current-window metrics from all imported data and latest import validation.
- Reworked the review queue into a filterable, card-based workflow so large review backlogs are manageable.
- Added real page navigation to the review queue, including page-aware save redirects so the workflow stays usable when clearing a large backlog.
- Tightened the review card UI density and redesigned the create-rule section into a cleaner, conditional rule builder for faster review decisions.
- Simplified rule creation language for everyday users and moved technical controls into an Advanced options section.
- Added plain-English help text and tooltip guidance for rule priority so users can safely keep defaults.
- Updated user-facing LOC wording to Line of Credit across dashboard/import labels, warnings, and seeded account naming.
- Replaced the fragile native browser tooltip with a reliable in-app hover/focus tooltip for rule-priority help.
- Added retroactive rule application to the review queue: when saving a rule, an "Also apply to other matching transactions" checkbox (checked by default) bulk-updates all other matching review-queue transactions in one step. Contains/exact rules use a single SQL UPDATE; regex rules iterate in Python. The flash message reports how many extra transactions were cleared.
- Fixed amount display in the review queue: debits now render as −$45.23 and credits as +$12.00 with color classes, replacing the raw signed number.
- Fixed the Zelle filter-bar row alignment in the review queue by adding an invisible spacer label above the checkbox.
- Added active nav-pill highlighting to the site header: the current page's pill is now filled teal using `request.endpoint` comparison in the base template.
- Removed the generic subtitle placeholder from the base template header.
- Added new page routes: `/transactions` (full transaction browser with filter/pagination/inline edit), `/rules` (rules management table with enable/disable/delete/inline edit), `/bills` (recurring bills CRUD). All three are linked in the site nav.
- Styled the file upload input on the Import page as a custom button+filename component instead of the default browser file picker.
- Added inline CSS cleanup: replaced all `style=""` attributes across every template with 23 new utility CSS classes in `base.html` (`.field-label`, `.meta-text`, `.card-note`, `.empty-state`, `.empty-cell`, `.row-between`, `.flex-wrap-row`, `.flex-row-sm`, `.input-narrow`, `.btn-action`, `.btn-warn`, `.form-narrow`, `.row-inactive`, `.window-active`, `.badge-warn`, `.label-spacer`, `.filter-checkbox-label`, `.filter-actions`, `.btn-filter`, `.btn-clear`, `.filter-grid-transactions`, `.pagination-meta`, `.text-sm`). The only remaining inline style is the confidence meter's `--meter-w` CSS custom property, which is inherently dynamic.
- Added an inline "add new category" option in the review form so users can create and apply categories without leaving the queue.
- Added backend support to create or reuse matching category names safely (case-insensitive) during review saves.
- Completed a deep review-card redesign for space efficiency: compact transaction summary, cleaner decision panel, lighter visual density, and improved action placement.
- Added an inline "Add new category" details flow to keep advanced inputs available without cluttering the primary review path.
- Added a dedicated view-route test suite covering dashboard/settings/bills/contacts/import/review endpoints and key redirect/error branches.
- Increased overall automated test coverage from 80% to 88%, with view-layer coverage improved from 55% to 90%.
- Fixed review-save scroll behavior by preserving and restoring scroll position so saving a card no longer jumps you to the top of the page.
- Added VS Code testing workspace settings for pytest discovery and one-click test runs from the editor.
- Fixed parsing for BECU dates that use two-digit years.
- Fixed mixed-account CSV imports so rows are filtered to the selected account instead of being imported wholesale.
- Fixed a dashboard service indentation regression introduced during refactoring.
- Fixed review queue usability issues caused by rendering too many inline forms at once without filters.
- Expanded import and dashboard test coverage for real BECU parsing, account filtering, LOC/Zelle handling, transfer fallback behavior, sanity warnings, and review queue pagination behavior.

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
