from datetime import date
from pathlib import Path

from app.services.categorization_service import apply_rules, fetch_rules
from app.services.import_service import import_csv, normalize_row, preview_import
from app.services.dashboard_service import build_dashboard


def test_csv_profile_mapping(database):
    account = database.execute("select * from accounts where id = 'acct-becu-checking'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-generic-debit-credit'").fetchone()
    row = {"Date": "2026-06-20", "Description": "Payroll", "Debit": "0", "Credit": "2034.70"}

    normalized = normalize_row(row, profile, account)

    assert normalized["transaction_date"] == "2026-06-20"
    assert normalized["description"] == "Payroll"
    assert float(normalized["amount"]) == 2034.70
    assert normalized["direction"] == "inflow"
    assert normalized["transaction_class"] == "income"


def test_transaction_hash_duplicate_detection(database):
    csv_payload = b"Date,Description,Amount,Balance\n06/19/2026,URBAN CITY COFFEE,-6.45,1500.00\n"

    first_report = import_csv(database, csv_payload, "becu.csv", "acct-becu-checking", "profile-becu-checking")
    second_report = import_csv(database, csv_payload, "becu.csv", "acct-becu-checking", "profile-becu-checking")

    assert first_report["new_transactions"] == 1
    assert second_report["duplicates_skipped"] == 1
    stored_count = database.execute("select count(*) as count from transactions").fetchone()["count"]
    assert stored_count == 1


def test_duplicate_detection_allows_same_day_same_amount_if_description_differs(database):
    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/19/2026,COFFEE SHOP A,-5.00,1500.00\n"
        b"06/19/2026,COFFEE SHOP B,-5.00,1495.00\n"
    )

    report = import_csv(database, csv_payload, "same-day.csv", "acct-becu-checking", "profile-becu-checking")

    assert report["new_transactions"] == 2
    assert report["duplicates_skipped"] == 0


def test_becu_csv_import(database):
    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/19/2026,SOUND PROP,2034.70,2500.00\n"
        b"06/20/2026,URBAN CITY COFFEE,-6.45,2493.55\n"
        b"06/21/2026,AMAZON,-42.00,2451.55\n"
    )

    report = import_csv(database, csv_payload, "becu-checking.csv", "acct-becu-checking", "profile-becu-checking")
    transactions = database.execute(
        """
        select transactions.description, transactions.transaction_class, transactions.needs_review, categories.name as category_name
        from transactions
        left join categories on categories.id = transactions.category_id
        order by transactions.transaction_date asc, transactions.description asc
        """
    ).fetchall()

    assert report["rows_read"] == 3
    assert report["new_transactions"] == 3
    assert report["needs_review_count"] == 1
    assert transactions[0]["category_name"] == "Paycheck"
    assert transactions[1]["category_name"] == "Coffee Shops"
    assert transactions[2]["category_name"] == "Needs Review"
    assert transactions[2]["needs_review"] == 1


def test_becu_sample_import_totals(database):
    sample_path = Path(__file__).parent / "fixtures" / "becu_may_june_sample.csv"
    report = import_csv(
        database,
        sample_path.read_bytes(),
        "becu_may_june_sample.csv",
        "acct-becu-checking",
        "profile-becu-checking",
    )

    debug = report["debug_report"]
    assert debug["imported_file_name"] == "becu_may_june_sample.csv"
    assert debug["total_rows_read"] == 12
    assert float(debug["inflow_total"]) == 2914.70
    assert float(debug["outflow_total"]) == 2520.57
    assert round(float(debug["net_total"]), 2) == 394.13
    assert "normal_income_total" in debug
    assert "reimbursement_total" in debug
    assert "debt_draw_total" in debug
    assert "normal_expense_total" in debug
    assert "debt_payment_total" in debug
    assert "transfer_ignore_total" in debug
    assert "review_unknown_total" in debug
    assert "coffee_shops_total" in debug
    assert "groceries_total" in debug
    assert "fast_food_total" in debug
    assert "restaurants_total" in debug
    assert "total_food" in debug
    assert "loc_draws_detected" in debug
    assert "credit_card_payments_detected" in debug
    assert "transactions_needing_review_details" in debug


def test_categorization_rules_priority(database):
    rules = fetch_rules(database)
    transaction = {
        "description": "SAFEWAY FUEL #1234",
        "transaction_class": "expense",
        "category_id": None,
        "category_name": None,
        "needs_review": False,
        "review_note": None,
    }

    categorized = apply_rules(transaction, rules)

    assert categorized["category_name"] == "Fuel"
    assert categorized["matched_rule_pattern"] == "SAFEWAY FUEL"


def test_preview_returns_first_five_rows(database):
    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/19/2026,SOUND PROP,2034.70,2500.00\n"
        b"06/20/2026,URBAN CITY COFFEE,-6.45,2493.55\n"
        b"06/21/2026,QFC,-54.22,2439.33\n"
        b"06/22/2026,WINCO,-91.10,2348.23\n"
        b"06/23/2026,ZIPLY,-82.00,2266.23\n"
        b"06/24/2026,AMAZON,-42.00,2224.23\n"
    )

    preview = preview_import(database, csv_payload, "acct-becu-checking", "profile-becu-checking")

    assert len(preview) == 5
    assert preview[0]["category_name"] == "Paycheck"
    assert preview[1]["category_name"] == "Coffee Shops"
    assert preview[0]["transaction_hash"]
    assert preview[0]["account_name"] == "BECU Checking"
    assert "matched_rule" in preview[0]


def test_credit_card_positive_purchase_profile(database):
    account = database.execute("select * from accounts where id = 'acct-becu-credit-card'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-credit-card-positive-purchases'").fetchone()
    row = {"Date": "2026-06-20", "Description": "RESTAURANT CHARGE", "Amount": "25.20"}

    normalized = normalize_row(row, profile, account)

    assert float(normalized["amount"]) == -25.20
    assert normalized["transaction_class"] == "expense"
    assert normalized["direction"] == "outflow"


def test_debit_credit_column_profile(database):
    account = database.execute("select * from accounts where id = 'acct-becu-checking'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-generic-debit-credit'").fetchone()
    expense_row = {"Date": "2026-06-20", "Description": "GROCERY", "Debit": "55.10", "Credit": "0"}

    normalized = normalize_row(expense_row, profile, account)

    assert float(normalized["amount"]) == -55.10
    assert normalized["transaction_class"] == "expense"


def test_import_preview_output_fields(database):
    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/19/2026,SOUND PROP,2034.70,2500.00\n"
    )

    preview = preview_import(database, csv_payload, "acct-becu-checking", "profile-becu-checking")
    row = preview[0]

    assert row["row_number"] == 1
    assert row["transaction_date"] == "2026-06-19"
    assert row["posted_date"] is None
    assert row["description"] == "SOUND PROP"
    assert row["amount"] == "2034.70"
    assert row["direction"] == "inflow"
    assert row["account_name"] == "BECU Checking"
    assert row["transaction_hash"]
    assert row["matched_rule"] == "SOUND PROP"
    assert row["category_name"] == "Paycheck"
    assert row["transaction_class"] == "income"
    assert row["needs_review"] is False


def test_becu_real_export_profile_parses_two_digit_year_and_type_sign(database):
    account = database.execute("select * from accounts where id = 'acct-becu-checking'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-becu-checking'").fetchone()
    row = {
        "Date": "6/19/26",
        "Description": "Zelle Transfer",
        "Original Description": "Transfer Withdrawal -  Zelle CHRISTOPH FRY (800)233-2328",
        "Amount": "220",
        "Type": "Debit",
        "Memo": "Zelle CHRISTOPH FRY (800)233-2328",
    }

    normalized = normalize_row(row, profile, account)

    assert normalized["transaction_date"] == "2026-06-19"
    assert normalized["description"] == "Transfer Withdrawal - Zelle CHRISTOPH FRY (800)233-2328"
    assert float(normalized["amount"]) == -220.00
    assert normalized["direction"] == "outflow"
    assert normalized["transaction_class"] == "transfer"


def test_becu_real_export_import_uses_original_description_and_credit_type(database):
    csv_payload = (
        b"Date,Description,Original Description,Amount,Type,Parent Category,Category,Account,Tags,Memo,Pending\n"
        b"6/18/26,Sound Prop Serv,External Deposit - SOUND PROP SERV ACH - ACH,2034.7,Credit,Income,Paycheck,5651 * Primary Checking,,,false\n"
    )

    preview = preview_import(database, csv_payload, "acct-becu-checking", "profile-becu-checking")

    assert len(preview) == 1
    assert preview[0]["transaction_date"] == "2026-06-18"
    assert preview[0]["description"] == "External Deposit - SOUND PROP SERV ACH - ACH"
    assert preview[0]["amount"] == "2034.70"
    assert preview[0]["transaction_class"] == "income"
    assert preview[0]["category_name"] == "Paycheck"


def test_becu_real_export_filters_rows_to_selected_account(database):
    csv_payload = (
        b"Date,Description,Original Description,Amount,Type,Parent Category,Category,Account,Tags,Memo,Pending\n"
        b"6/18/26,Sound Prop Serv,External Deposit - SOUND PROP SERV ACH - ACH,2034.7,Credit,Income,Paycheck,5651 * Primary Checking,,,false\n"
        b"6/17/26,Interest Income,Dividend/Interest,0.36,Credit,Income,Interest Income,5643 * Savings Account,,,false\n"
    )

    preview = preview_import(database, csv_payload, "acct-becu-checking", "profile-becu-checking")

    assert len(preview) == 1
    assert preview[0]["account_name"] == "BECU Checking"
    assert preview[0]["description"] == "External Deposit - SOUND PROP SERV ACH - ACH"


def test_transfer_rows_default_to_transfers_ignore_without_review(database):
    csv_payload = (
        b"Date,Description,Original Description,Amount,Type,Parent Category,Category,Account,Tags,Memo,Pending\n"
        b"6/20/26,Transfer to Savings Account 5643,Withdrawal - Online Banking Transfer To XXXXXX5643 SAV,88,Debit,Transfer,Transfer,5651 * Primary Checking,,,false\n"
    )

    preview = preview_import(database, csv_payload, "acct-becu-checking", "profile-becu-checking")

    assert len(preview) == 1
    assert preview[0]["transaction_class"] == "transfer"
    assert preview[0]["category_name"] == "Transfers / Ignore"
    assert preview[0]["needs_review"] is False


def test_loc_draw_is_not_income(database):
    account = database.execute("select * from accounts where id = 'acct-becu-loc'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-generic-signed'").fetchone()
    row = {"Date": "2026-06-20", "Description": "LOC ADVANCE", "Amount": "250.00"}

    normalized = normalize_row(row, profile, account)

    assert normalized["transaction_class"] == "debt_draw"
    assert normalized["transaction_class"] != "income"


def test_loc_payment_is_not_normal_spending(database):
    account = database.execute("select * from accounts where id = 'acct-becu-loc'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-generic-signed'").fetchone()
    row = {"Date": "2026-06-20", "Description": "ONLINE PAYMENT", "Amount": "-175.00"}

    normalized = normalize_row(row, profile, account)

    assert normalized["transaction_class"] == "debt_payment"
    assert normalized["transaction_class"] != "expense"


def test_loc_interest_is_fee_interest(database):
    account = database.execute("select * from accounts where id = 'acct-becu-loc'").fetchone()
    profile = database.execute("select * from import_profiles where id = 'profile-generic-signed'").fetchone()
    row = {"Date": "2026-06-20", "Description": "FINANCE CHARGE", "Amount": "-12.34"}

    normalized = normalize_row(row, profile, account)

    assert normalized["transaction_class"] == "fee_interest"


def test_zelle_from_known_roommate_suggests_reimbursement_but_needs_review(database):
    database.execute(
        """
        insert into contacts (id, name, relationship_type, default_category_id, auto_apply, active, notes)
        values ('contact-roommate', 'ALEX', 'roommate', 'category-household-reimbursement', 1, 1, 'Roommate reimbursements')
        """
    )
    database.commit()

    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/20/2026,ZELLE FROM ALEX,85.00,1500.00\n"
    )

    report = import_csv(database, csv_payload, "zelle-roommate.csv", "acct-becu-checking", "profile-becu-checking")
    transaction = database.execute(
        "select transaction_class, category_id, needs_review, review_note from transactions where source_import_id = ?",
        (report["import_id"],),
    ).fetchone()

    assert transaction["transaction_class"] == "reimbursement"
    assert transaction["category_id"] == "category-household-reimbursement"
    assert transaction["needs_review"] == 1
    assert "Suggested category: Household Reimbursement" in transaction["review_note"]


def test_unknown_zelle_remains_needs_review(database):
    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/20/2026,ZELLE TO SOMEONE,-45.00,1500.00\n"
    )

    report = import_csv(database, csv_payload, "zelle-unknown.csv", "acct-becu-checking", "profile-becu-checking")
    transaction = database.execute(
        "select transaction_class, category_id, needs_review from transactions where source_import_id = ?",
        (report["import_id"],),
    ).fetchone()

    assert transaction["transaction_class"] == "needs_review"
    assert transaction["category_id"] is None
    assert transaction["needs_review"] == 1


def test_zelle_reimbursement_excluded_from_normal_income_totals(database):
    database.execute(
        """
        insert into contacts (id, name, relationship_type, default_category_id, auto_apply, active, notes)
        values ('contact-roommate-income', 'ALEX', 'roommate', 'category-household-reimbursement', 1, 1, 'Roommate reimbursements')
        """
    )
    database.commit()

    csv_payload = (
        b"Date,Description,Amount,Balance\n"
        b"06/20/2026,ZELLE FROM ALEX,100.00,1500.00\n"
    )

    import_csv(database, csv_payload, "zelle-reimbursement.csv", "acct-becu-checking", "profile-becu-checking")
    dashboard = build_dashboard(database, today=date(2026, 6, 20))

    assert float(dashboard["summary"]["normal_income_total"]) == 0.0
    assert float(dashboard["summary"]["reimbursement_total"]) == 100.0