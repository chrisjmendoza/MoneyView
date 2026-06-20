from datetime import date
from decimal import Decimal

from app.services.dashboard_service import build_dashboard
from app.services.pay_period_service import calculate_pay_period
from app.services.safe_to_spend_service import calculate_safe_to_spend


def test_safe_to_spend_calculation():
    safe_to_spend = calculate_safe_to_spend(Decimal("2500.00"), Decimal("700.00"), Decimal("500.00"))
    assert safe_to_spend == Decimal("1300.00")


def test_pay_period_calculation_from_anchor():
    period = calculate_pay_period(date(2026, 6, 19), date(2026, 7, 2), "biweekly")

    assert period["current_payday"] == date(2026, 6, 19)
    assert period["next_payday"] == date(2026, 7, 3)
    assert period["pay_period_end"] == date(2026, 7, 2)


def test_dashboard_metrics(database):
    database.execute(
        "insert into balance_snapshots (id, account_id, snapshot_date, balance) values ('bal-1', 'acct-becu-checking', '2026-06-19', 2500.00)"
    )
    database.execute(
        "insert into recurring_bills (id, name, expected_amount, due_day, frequency, category_id, active) values ('bill-1', 'Rent', 700.00, 20, 'monthly', 'category-rent', 1)"
    )
    database.execute(
        """
        insert into imports (id, account_id, import_profile_id, source_file_name, rows_read, new_transactions)
        values ('import-dashboard', 'acct-becu-checking', 'profile-becu-checking', 'seed.csv', 10, 10)
        """
    )
    database.execute(
        """
        insert into transactions (
          id, transaction_date, posted_date, account_id, description, raw_description, merchant, amount, direction,
          transaction_class, category_id, needs_review, review_note, matched_rule_id, matched_rule_pattern, transaction_hash, raw_csv_row_json, source_import_id
        ) values
        ('txn-1', '2026-06-19', null, 'acct-becu-checking', 'SOUND PROP', 'SOUND PROP', 'Sound Prop', 2034.70, 'inflow', 'income', 'category-paycheck', 0, null, null, null, 'hash-1', '{}', 'import-dashboard'),
        ('txn-2', '2026-06-20', null, 'acct-becu-checking', 'URBAN CITY COFFEE', 'URBAN CITY COFFEE', 'Urban City Coffee', -6.45, 'outflow', 'expense', 'category-coffee-shops', 0, null, null, null, 'hash-2', '{}', 'import-dashboard'),
        ('txn-3', '2026-06-21', null, 'acct-becu-checking', 'AMAZON', 'AMAZON', 'Amazon', -42.00, 'outflow', 'needs_review', null, 1, 'No categorization rule matched.', null, null, 'hash-3', '{}', 'import-dashboard'),
        ('txn-4', '2026-06-22', null, 'acct-becu-checking', 'BECU CREDIT CARD PAYMENT', 'BECU CREDIT CARD PAYMENT', 'Becu Credit Card Payment', -400.00, 'outflow', 'debt_payment', 'category-credit-card-payment', 0, null, null, null, 'hash-4', '{}', 'import-dashboard'),
        ('txn-5', '2026-06-23', null, 'acct-becu-checking', 'LOC ADVANCE', 'LOC ADVANCE', 'Loc Advance', 500.00, 'inflow', 'debt_draw', 'category-loc-draw', 0, null, null, null, 'hash-5', '{}', 'import-dashboard'),
        ('txn-6', '2026-06-24', null, 'acct-becu-checking', 'ZELLE FROM ROOMMATE', 'ZELLE FROM ROOMMATE', 'Zelle From Roommate', 100.00, 'inflow', 'reimbursement', 'category-household-reimbursement', 0, null, null, null, 'hash-6', '{}', 'import-dashboard')
        """
    )
    database.commit()

    dashboard = build_dashboard(database, today=date(2026, 6, 19))

    assert float(dashboard["summary"]["normal_income_total"]) == 2034.70
    assert float(dashboard["summary"]["reimbursement_total"]) == 100.00
    assert float(dashboard["summary"]["debt_draw_total"]) == 500.00
    assert float(dashboard["summary"]["debt_payment_total"]) == 400.00
    assert float(dashboard["summary"]["coffee_total"]) == 6.45
    assert float(dashboard["summary"]["unknown_review_total"]) == 42.00
    assert float(dashboard["summary"]["normal_expense_total"]) == 6.45
    assert dashboard["pay_period"]["next_payday"] == date(2026, 7, 3)
    assert dashboard["safe_to_spend"] == Decimal("1300")
    assert dashboard["data_confidence"]["needs_review_count"] == 1


def test_dashboard_exclusions_for_spending_and_income(database):
    database.execute(
        """
        insert into imports (id, account_id, import_profile_id, source_file_name, rows_read, new_transactions)
        values ('import-exclusion', 'acct-becu-checking', 'profile-becu-checking', 'exclude.csv', 4, 4)
        """
    )
    database.execute(
        """
        insert into transactions (
          id, transaction_date, posted_date, account_id, description, raw_description, merchant, amount, direction,
          transaction_class, category_id, needs_review, review_note, matched_rule_id, matched_rule_pattern, transaction_hash, raw_csv_row_json, source_import_id
        ) values
        ('txn-e1', '2026-06-20', null, 'acct-becu-checking', 'LOC ADVANCE', 'LOC ADVANCE', 'Loc Advance', 300.00, 'inflow', 'debt_draw', 'category-loc-draw', 0, null, null, null, 'hash-e1', '{}', 'import-exclusion'),
        ('txn-e2', '2026-06-20', null, 'acct-becu-checking', 'BECU CREDIT CARD PAYMENT', 'BECU CREDIT CARD PAYMENT', 'Becu Credit Card Payment', -250.00, 'outflow', 'debt_payment', 'category-credit-card-payment', 0, null, null, null, 'hash-e2', '{}', 'import-exclusion'),
        ('txn-e3', '2026-06-20', null, 'acct-becu-checking', 'ROOMMATE PAYBACK', 'ROOMMATE PAYBACK', 'Roommate Payback', 80.00, 'inflow', 'reimbursement', 'category-household-reimbursement', 0, null, null, null, 'hash-e3', '{}', 'import-exclusion'),
        ('txn-e4', '2026-06-20', null, 'acct-becu-checking', 'QFC', 'QFC', 'Qfc', -45.00, 'outflow', 'expense', 'category-groceries', 0, null, null, null, 'hash-e4', '{}', 'import-exclusion')
        """
    )
    database.commit()

    dashboard = build_dashboard(database, today=date(2026, 6, 20))

    assert float(dashboard["summary"]["normal_income_total"]) == 0.0
    assert float(dashboard["summary"]["debt_draw_total"]) == 300.0
    assert float(dashboard["summary"]["debt_payment_total"]) == 250.0
    assert float(dashboard["summary"]["reimbursement_total"]) == 80.0
    assert float(dashboard["summary"]["normal_expense_total"]) == 45.0
    assert float(dashboard["summary"]["food_total"]) == 45.0


def test_pay_period_filtering(database):
    database.execute(
        """
        insert into imports (id, account_id, import_profile_id, source_file_name, rows_read, new_transactions)
        values ('import-window', 'acct-becu-checking', 'profile-becu-checking', 'window.csv', 3, 3)
        """
    )
    database.execute(
        """
        insert into transactions (
          id, transaction_date, posted_date, account_id, description, raw_description, merchant, amount, direction,
          transaction_class, category_id, needs_review, review_note, matched_rule_id, matched_rule_pattern, transaction_hash, raw_csv_row_json, source_import_id
        ) values
        ('txn-w1', '2026-06-10', null, 'acct-becu-checking', 'QFC', 'QFC', 'Qfc', -40.00, 'outflow', 'expense', 'category-groceries', 0, null, null, null, 'hash-w1', '{}', 'import-window'),
        ('txn-w2', '2026-06-20', null, 'acct-becu-checking', 'QFC', 'QFC', 'Qfc', -50.00, 'outflow', 'expense', 'category-groceries', 0, null, null, null, 'hash-w2', '{}', 'import-window'),
        ('txn-w3', '2026-06-24', null, 'acct-becu-checking', 'QFC', 'QFC', 'Qfc', -60.00, 'outflow', 'expense', 'category-groceries', 0, null, null, null, 'hash-w3', '{}', 'import-window')
        """
    )
    database.commit()

    current_period = build_dashboard(database, today=date(2026, 6, 24), window="current_pay_period")
    previous_period = build_dashboard(database, today=date(2026, 6, 24), window="previous_pay_period")
    current_month = build_dashboard(database, today=date(2026, 6, 24), window="current_month")

    assert float(current_period["summary"]["normal_expense_total"]) == 110.00
    assert float(previous_period["summary"]["normal_expense_total"]) == 40.00
    assert float(current_month["summary"]["normal_expense_total"]) == 150.00


def test_dashboard_sanity_warnings(database):
    database.execute(
        """
        insert into imports (id, account_id, import_profile_id, source_file_name, rows_read, new_transactions)
        values ('import-sanity', 'acct-becu-checking', 'profile-becu-checking', 'sanity.csv', 5, 5)
        """
    )
    database.execute(
        """
        insert into transactions (
          id, transaction_date, posted_date, account_id, description, raw_description, merchant, amount, direction,
          transaction_class, category_id, needs_review, review_note, matched_rule_id, matched_rule_pattern, transaction_hash, raw_csv_row_json, source_import_id
        ) values
        ('txn-s1', '2026-06-20', null, 'acct-becu-checking', 'ROOMMATE PAYBACK', 'ROOMMATE PAYBACK', 'Roommate Payback', 120.00, 'inflow', 'income', 'category-household-reimbursement', 0, null, null, null, 'hash-s1', '{}', 'import-sanity'),
        ('txn-s2', '2026-06-20', null, 'acct-becu-checking', 'LOC ADVANCE', 'LOC ADVANCE', 'Loc Advance', 300.00, 'inflow', 'income', 'category-loc-draw', 0, null, null, null, 'hash-s2', '{}', 'import-sanity'),
        ('txn-s3', '2026-06-20', null, 'acct-becu-checking', 'CC PAYMENT', 'CC PAYMENT', 'Cc Payment', -250.00, 'outflow', 'expense', 'category-credit-card-payment', 0, null, null, null, 'hash-s3', '{}', 'import-sanity'),
        ('txn-s4', '2026-06-20', null, 'acct-becu-checking', 'INTERNAL TRANSFER', 'INTERNAL TRANSFER', 'Internal Transfer', -200.00, 'outflow', 'expense', 'category-transfers-ignore', 0, null, null, null, 'hash-s4', '{}', 'import-sanity'),
        ('txn-s5', '2026-06-20', null, 'acct-becu-checking', 'UNKNOWN MERCHANT', 'UNKNOWN MERCHANT', 'Unknown Merchant', -350.00, 'outflow', 'needs_review', null, 1, 'No categorization rule matched.', null, null, 'hash-s5', '{}', 'import-sanity'),
        ('txn-s6', '2026-06-20', null, 'acct-becu-checking', 'ANOTHER UNKNOWN', 'ANOTHER UNKNOWN', 'Another Unknown', -20.00, 'outflow', 'needs_review', null, 1, 'No categorization rule matched.', null, null, 'hash-s6', '{}', 'import-sanity')
        """
    )
    database.commit()

    dashboard = build_dashboard(database, today=date(2026, 6, 20))
    warning_codes = {warning["code"] for warning in dashboard["sanity_warnings"]}

    assert "reimbursements_counted_as_income" in warning_codes
    assert "loc_draws_counted_as_income" in warning_codes
    assert "credit_card_payments_as_expense" in warning_codes
    assert "transfers_as_expense" in warning_codes
    assert "review_total_high" in warning_codes
    assert "review_ratio_high" in warning_codes
    assert "missing_checking_balance" in warning_codes