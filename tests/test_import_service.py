from pathlib import Path

from app.services.categorization_service import apply_rules, fetch_rules
from app.services.import_service import import_csv, normalize_row, preview_import


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