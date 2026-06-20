import argparse
from datetime import date
from pathlib import Path

from app import create_app
from app.db import get_db
from app.services.dashboard_service import build_dashboard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the live MoneyView dashboard state from a local SQLite DB.")
    parser.add_argument("--db", default="data/moneyview.sqlite3", help="Path to the MoneyView SQLite database.")
    parser.add_argument(
        "--window",
        default="current_pay_period",
        choices=["current_pay_period", "previous_pay_period", "current_month"],
        help="Dashboard window to inspect.",
    )
    parser.add_argument("--today", default=date.today().isoformat(), help="Reference date in YYYY-MM-DD format.")
    return parser.parse_args()


def money(value) -> str:
    return f"${float(value or 0):.2f}"


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    app = create_app({"TESTING": True, "DATABASE_PATH": db_path})

    with app.app_context():
        dashboard = build_dashboard(get_db(), today=date.fromisoformat(args.today), window=args.window)

    print("=== MoneyView Dashboard Inspection ===")
    print(f"DB: {db_path}")
    print(f"Window: {args.window}")
    print(f"Range: {dashboard['range']['start']} to {dashboard['range']['end']}")
    print()

    latest_import = dashboard.get("latest_import")
    if latest_import:
        print("Latest import")
        print(f"  Imported at: {latest_import['imported_at']}")
        print(f"  Account: {latest_import['account_name']}")
        print(f"  Profile: {latest_import['profile_name']}")
        print(f"  Rows read: {latest_import['rows_read']}")
        print(f"  New transactions: {latest_import['new_transactions']}")
        print(f"  Duplicates skipped: {latest_import['duplicates_skipped']}")
        print(f"  Needs review from import: {latest_import['needs_review_count']}")
        print(f"  Errors: {latest_import['errors_count']}")
        print()

    print("Current window quality")
    print(f"  Categorized: {dashboard['data_confidence']['categorized_transactions']} / {dashboard['data_confidence']['total_transactions']}")
    print(f"  Review count: {dashboard['data_confidence']['needs_review_count']}")
    print(f"  Review total: {money(dashboard['data_confidence']['needs_review_total'])}")
    print(f"  Percent categorized: {dashboard['data_confidence']['percent_categorized']:.2f}%")
    print()

    print("All imported data quality")
    print(f"  Total transactions: {dashboard['all_data_confidence']['total_transactions']}")
    print(f"  Review count: {dashboard['all_data_confidence']['needs_review_count']}")
    print(f"  Review total: {money(dashboard['all_data_confidence']['needs_review_total'])}")
    print(f"  Percent categorized: {dashboard['all_data_confidence']['percent_categorized']:.2f}%")
    print()

    print("Cash flow snapshot")
    print(f"  Income: {money(dashboard['summary']['normal_income_total'])}")
    print(f"  Reimbursements: {money(dashboard['summary']['reimbursement_total'])}")
    print(f"  Normal expenses: {money(dashboard['summary']['normal_expense_total'])}")
    print(f"  Transfers / ignored: {money(dashboard['summary']['transfer_ignore_total'])}")
    print(f"  Unknown / review: {money(dashboard['summary']['unknown_review_total'])}")
    print(f"  Safe to spend: {money(dashboard['safe_to_spend'])}")
    print()

    print(f"Sanity warnings: {dashboard['sanity_warning_count']}")
    for warning in dashboard['sanity_warnings']:
        print(f"  - {warning['code']}: {warning['message']}")


if __name__ == "__main__":
    main()
