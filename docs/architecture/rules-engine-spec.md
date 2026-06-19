# Rules Engine Specification

## Goals
- Keep categorization and classification generic.
- Store rules in database, not hardcoded conditions.
- Apply deterministic priority ordering.

## Rule Inputs
- description
- merchant
- amount
- account_type
- institution_id
- source_name

## Match Operators
- contains
- starts_with
- exact_match
- regex
- amount_greater_than
- account_type
- institution

## Rule Actions
- set category
- set transaction_class
- set needs_review

## Priority Model
- Integer priority (higher wins).
- Tie-break by updated_at desc, then id asc for deterministic behavior.
- Stop on first terminal match by default.

## Suggested Tables
### categorization_rules
- id
- user_id (nullable for global defaults)
- name
- enabled
- priority
- field_name
- operator
- match_value
- amount_threshold
- account_type
- institution_id
- set_category
- set_transaction_class
- set_needs_review
- created_at
- updated_at

### rule_runs (optional)
- id
- import_batch_id
- transactions_evaluated
- rules_evaluated
- created_at

## Application Sequence
1. Start with transaction defaults.
2. Evaluate rules in descending priority.
3. Apply first matching rule (or continue if non-terminal mode is enabled later).
4. Mark unknown category as Needs Review.

## Example Rules
- If description contains URBAN CITY COFFEE -> category Coffee Shops, class Expense.
- If description contains CHASE CREDIT CRD -> category Credit Card Payment, class Debt Payment.
- If description contains ZELLE FROM -> category Reimbursement, class Household Reimbursement, needs_review true.
