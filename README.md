# MoneyView

Local-first finance CSV dashboard for reviewing imports, categorizing transactions, and checking a realistic safe-to-spend picture without sending banking data to a third-party service.

## What It Does

- Imports bank CSV exports into a local SQLite database.
- Previews rows before import so parsing problems are visible early.
- Categorizes transactions with rules plus review-required fallbacks.
- Highlights ambiguous transactions in a review queue.
- Shows dashboard summaries for the current pay window and imported history.
- Keeps real financial data local to the machine.

## Tech Stack

- Python 3.11+
- Flask
- SQLite
- Pytest

## Quick Start

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Activate it

On Git Bash:

```bash
source .venv/Scripts/activate
```

On PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install the project

```bash
pip install -e .
```

### 4. Run the app

```bash
python main.py
```

Then open:

```text
http://127.0.0.1:5000
```

## Main Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — pay period summary, safe-to-spend, sanity warnings |
| `/import` | CSV import — preview then commit, with per-row debug output |
| `/review` | Review queue — triage flagged and uncategorized transactions |
| `/transactions` | Transaction browser — browse, filter, and re-classify any transaction |
| `/rules` | Rules management — view, edit, enable/disable, and delete categorization rules |
| `/bills` | Recurring bills — create, edit, and delete bills used in safe-to-spend math |

## How To Test With a CSV

1. Start the app with `python main.py`.
2. Open `/import`.
3. Choose an account and an import profile.
4. Upload a CSV and preview it first.
5. If the preview looks correct, run the import.
6. Open `/review` to triage transactions flagged for review.
7. Return to `/` to inspect dashboard totals and warnings.
8. Use `/transactions` to browse or re-classify any imported transaction.
9. Use `/rules` to manage the rules that drive auto-categorization.

## Running Tests

```bash
pytest -q
```

## Real Data and Privacy

MoneyView is designed to be local-first.

- Do not commit real bank CSV files.
- Do not commit real SQLite database files.
- Use `tests/fixtures/` for synthetic fixtures only.
- Use local `data/` storage for personal imports.

See `PRIVACY.md` for the full workflow, including anonymizing CSVs and running local validation scripts.

## Helper Scripts

```bash
python scripts/validate_real_csv.py --csv path/to/file.csv --profile "BECU Checking CSV" --account "BECU Checking"
python scripts/anonymize_csv.py --csv path/to/real.csv --out tests/fixtures/anonymized_case.csv
python scripts/inspect_dashboard.py
```

## Project Layout

```text
app/                  Flask app, services, views, templates
db/schema/            SQLite schema
docs/architecture/    Import and rules-engine notes
scripts/              Local validation and utility scripts
tests/                Automated tests and fixtures
main.py               App entry point
```

## Configuration

Set `SECRET_KEY` in your environment before running on any network-accessible address:

```bash
export SECRET_KEY="your-random-secret-here"   # Git Bash / macOS / Linux
$env:SECRET_KEY = "your-random-secret-here"   # PowerShell
```

The app warns loudly at startup if the key is unset and falls back to an insecure default that is only appropriate for local development.

## Current Status

Core workflow is complete:

- Profile-driven CSV import with preview, deduplication, and per-row debug output
- Priority-ordered categorization rules engine with Zelle and LOC contextual overrides
- Review queue with filters, pagination, inline rule creation, and scroll preservation
- Transaction browser for browsing, filtering, and re-classifying any historical transaction
- Rules management page for viewing, editing, toggling, and deleting all active rules
- Bills management page for maintaining the recurring bills list used in safe-to-spend math
- Dashboard with pay-period and month windows, sanity warnings, and data confidence metrics
- WAL-mode SQLite for reliable concurrent reads during development

## Roadmap

### Next Up

- Import history page — list past imports and roll back (delete) an import and its transactions.
- CSRF protection on all forms.
- Input validation on `/settings` (date format and decimal fields).
- Net refunds against category totals (currently refund-class positive amounts are excluded).
- Non-monthly bill frequency support in safe-to-spend math (weekly, annual).
- Remove hardcoded employer name from sanity warning — make it a user setting.

### Later

- Budget vs. actual per category (set a monthly target, track real spend against it).
- Net worth snapshot view (assets − liabilities across all accounts).
- Annual projections from current pay-period spend rate.
- Multi-period trend view (3-month rolling category averages).
- Column-mapping wizard for unsupported CSV layouts.
- Profile auto-suggestion based on detected CSV headers.
- Export filtered transactions to CSV.

## Development Notes

- MoneyView is intentionally local-first and privacy-sensitive.
- Real financial CSVs and local database files should stay out of source control.
- The fastest feedback loop is `python main.py` for manual testing and `pytest -q` for regression checks.

## GitHub

Repository:

```text
https://github.com/chrisjmendoza/MoneyView
```
