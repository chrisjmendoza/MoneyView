# MoneyView Privacy Guardrails

MoneyView is intentionally local-first. Use this guide when validating with real bank exports.

## Do Not Commit Private Financial Data

- Real bank CSV files should never be committed.
- Real SQLite database files should never be committed.
- Use synthetic fixtures in `tests/fixtures/` for automated tests.
- Use local-only `data/` or `instance/` folders for private imports.

## Real CSV Smoke Test Workflow (Developer-Only)

Use the validation script with a local CSV path:

```bash
python scripts/validate_real_csv.py --csv path/to/file.csv --profile "BECU Checking CSV" --account "BECU Checking"
```

Notes:

- This creates/uses a local temporary SQLite database for validation.
- It imports CSV rows, runs categorization, and prints a terminal debug report.
- It does not require committing the CSV.
- It does not write private reports into the repo unless you explicitly redirect output yourself.

## Real CSV Import Review Checklist

After importing a real CSV, verify:

1. Date range is correct.
2. Paychecks are categorized as income.
3. Roommate payments are reimbursement, not income.
4. LOC movement is debt_draw or debt_payment, not income/expense.
5. Credit card payments are debt_payment, not spending.
6. Coffee shop merchants are captured.
7. Grocery stores are captured.
8. Amazon/PayPal/Bicycle Centres remain review-required.
9. Unknown total is low enough to trust the dashboard.
10. Safe-to-spend uses a manually entered checking balance.

## Optional Fixture Sharing

If you find a parser/categorization bug with a private CSV, use:

```bash
python scripts/anonymize_csv.py --csv path/to/real.csv --out tests/fixtures/anonymized_case.csv
```

This keeps useful structure for debugging while removing identifying details.
