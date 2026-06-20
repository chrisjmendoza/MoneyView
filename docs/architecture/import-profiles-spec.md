# Import Profiles Specification

## Objective
Define reusable profile metadata for parsing diverse CSV formats into MoneyView's canonical transaction model.

## Profile Schema
- id (uuid)
- name (string)
- institution_id (uuid, nullable for generic profile)
- account_type (enum: checking, savings, credit_card, loan, line_of_credit, other)
- date_column (string, nullable)
- posted_date_column (string, nullable)
- account_column (string, nullable)
- description_column (string, nullable)
- amount_column (string, nullable)
- type_column (string, nullable)
- debit_column (string, nullable)
- credit_column (string, nullable)
- balance_column (string, nullable)
- amount_sign_rule (enum)
- date_format (string, nullable)
- has_header (boolean)
- active (boolean)
- notes (string, nullable)
- created_at (timestamp)
- updated_at (timestamp)

## Amount Sign Rule Contract
### signed_amount
- Read numeric value from amount_column as-is.

### signed_amount_or_type_column
- Read numeric value from amount_column.
- If type_column is present and row type is `Credit`, force positive.
- If type_column is present and row type is `Debit`, force negative.
- If type_column is missing, fall back to signed_amount behavior.

### debit_credit_columns
- amount = credit - debit
- Missing side defaults to 0.

### credit_card_positive_purchases
- Positive value means expense (debt increase).
- Negative value means payment/refund depending on text/rule context.

### credit_card_negative_purchases
- Negative value means expense.
- Positive value means payment/refund depending on text/rule context.

## Normalization Expectations
All profile adapters produce:
- Canonical amount sign for internal analytics.
- direction set to inflow or outflow.
- Optional row-level account filtering when account_column is present.
- stable transaction_hash for de-duplication.
- raw_source_data JSON snapshot of original row.

## Header Signature Recognition (Later)
Optional table import_profile_aliases can store a normalized header signature and confidence for auto-suggesting a profile.

## Column Mapping Wizard (Future)
If no profile matches:
1. Ask user to map required fields.
2. Ask account type.
3. Ask amount sign rule.
4. Preview normalized sample.
5. Save as reusable profile.
