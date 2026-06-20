# MoneyView Generic CSV Import Architecture

## Purpose
Design MoneyView as a generic financial CSV importer with user configuration layered on top.

## Core Pipeline
1. Any financial CSV
2. Import profile / column mapping
3. Canonical transaction model
4. Categorization rules
5. Dashboard / reports

## Design Principles
- Keep source data, normalized data, and personal rules separate.
- Normalize all imported rows into one canonical transaction shape.
- Keep institution-specific adapters focused on parsing and normalization only.
- Keep categories, budgets, and dashboard cards user-editable.

## Canonical Transaction Model
All CSV imports normalize to this internal model:
- transaction_date
- posted_date
- description
- merchant
- amount
- direction
- account_id
- institution_id
- source_name
- category
- transaction_class
- needs_review
- raw_source_data
- transaction_hash

## Layer Boundaries
- Raw source data: exact CSV row values and metadata.
- Normalized transactions: canonical model used by all internal logic.
- Personal configuration: categories, budgets, pay schedule, and dashboard options.

## Import Profiles
Each profile defines CSV interpretation and amount behavior.

Fields:
- profile_name
- institution
- account_type
- date_column
- posted_date_column
- account_column
- description_column
- amount_column
- type_column
- debit_column
- credit_column
- balance_column
- amount_sign_rule
- date_format
- has_header_row
- notes

## Amount Sign Rules
Supported strategies:
- signed_amount
- signed_amount_or_type_column
- debit_credit_columns
- credit_card_positive_purchases
- credit_card_negative_purchases

## Import Workflow (MVP-compatible)
1. Upload CSV
2. Select account or create account
3. Choose import profile
4. Preview detected columns
5. Import transactions
6. Skip duplicates
7. Apply rules
8. Review unknowns
9. Generate dashboard

## Adapters
Initial:
- BECU Checking/Savings
- BECU Credit Card
- Chase Credit Card
- Generic CSV

Later:
- Kitsap Credit Union
- Capital One
- Discover
- Rocket Money export
- Monarch export
- YNAB export

## Anti-Pattern to Avoid
Do not branch on filename or institution string in importer flow.

Bad:
if "BECU" in file_name: do_becu_logic()

Good:
profile = selected_import_profile
transactions = normalize_csv(file, profile)

## MVP Build Order
1. Canonical transaction model
2. BECU CSV profile
3. BECU checking import
4. Rule engine pass
5. Dashboard basics
6. Chase credit card profile
7. Generic mapping screen
8. Additional account support
