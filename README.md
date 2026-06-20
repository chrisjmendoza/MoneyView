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

- `/` dashboard
- `/import` import preview and CSV import workflow
- `/review` review queue for transactions that still need human decisions

## How To Test With a CSV

1. Start the app with `python main.py`.
2. Open `/import`.
3. Choose an account.
4. Choose an import profile.
5. Upload a CSV and preview it first.
6. If the preview looks correct, run the import.
7. Open `/review` to clean up transactions that still need classification.
8. Return to `/` to inspect dashboard totals and warnings.

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

## Current Status

The project currently focuses on:

- BECU-friendly CSV import handling
- safer LOC and Zelle review behavior
- a review-first workflow for ambiguous transactions
- dashboard trust improvements and import validation

## GitHub

Repository:

```text
https://github.com/chrisjmendoza/MoneyView
```
