import argparse
import tempfile
from pathlib import Path

from app import create_app
from app.db import get_db
from app.services.import_service import import_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a manual real-CSV smoke test against a local SQLite DB.")
    parser.add_argument("--csv", required=True, help="Path to the local CSV file to validate.")
    parser.add_argument("--profile", required=True, help="Import profile name or ID (for example: BECU Checking CSV).")
    parser.add_argument("--account", required=True, help="Account name or ID (for example: BECU Checking).")
    parser.add_argument("--db", help="Optional local SQLite DB path. If omitted, a temporary DB is used.")
    parser.add_argument("--keep-db", action="store_true", help="Keep temporary DB directory after run (only applies without --db).")
    return parser.parse_args()


def resolve_profile_id(database, profile_selector: str) -> tuple[str, str]:
    profile = database.execute(
        """
        select id, name
        from import_profiles
        where active = 1 and (id = ? or name = ?)
        order by name asc
        limit 1
        """,
        (profile_selector, profile_selector),
    ).fetchone()
    if not profile:
        available = database.execute(
            "select name from import_profiles where active = 1 order by institution asc, name asc"
        ).fetchall()
        names = ", ".join(row["name"] for row in available)
        raise ValueError(f"Unknown profile '{profile_selector}'. Available profiles: {names}")
    return profile["id"], profile["name"]


def resolve_account_id(database, account_selector: str) -> tuple[str, str]:
    account = database.execute(
        """
        select id, name
        from accounts
        where active = 1 and (id = ? or name = ?)
        order by name asc
        limit 1
        """,
        (account_selector, account_selector),
    ).fetchone()
    if not account:
        available = database.execute("select name from accounts where active = 1 order by name asc").fetchall()
        names = ", ".join(row["name"] for row in available)
        raise ValueError(f"Unknown account '{account_selector}'. Available accounts: {names}")
    return account["id"], account["name"]


def money(value) -> str:
    return f"${float(value or 0):.2f}"


def print_debug_report(csv_path: Path, debug_report: dict) -> None:
    print("\n=== MoneyView Real CSV Smoke Test ===")
    print(f"Selected file: {csv_path}")
    print(f"Account: {debug_report['selected_account']}")
    print(f"Import profile: {debug_report['selected_import_profile']}")
    print(
        "Detected date range: "
        f"{debug_report['date_range_detected']['start'] or '--'} to {debug_report['date_range_detected']['end'] or '--'}"
    )
    print(f"Rows read: {debug_report['total_rows_read']}")
    print(f"New transactions: {debug_report['new_transactions_inserted']}")
    print(f"Duplicates skipped: {debug_report['duplicates_skipped']}")
    print(f"Errors: {debug_report['errors']['count']}")
    if debug_report["errors"]["details"]:
        for line in debug_report["errors"]["details"]:
            print(f"  - {line}")

    print(f"Inflow total: {money(debug_report['inflow_total'])}")
    print(f"Outflow total: {money(debug_report['outflow_total'])}")
    print(f"Net total: {money(debug_report['net_total'])}")

    print(f"Normal income total: {money(debug_report['normal_income_total'])}")
    print(f"Reimbursement total: {money(debug_report['reimbursement_total'])}")
    print(f"Debt draw total: {money(debug_report['debt_draw_total'])}")
    print(f"Normal expense total: {money(debug_report['normal_expense_total'])}")
    print(f"Debt payment total: {money(debug_report['debt_payment_total'])}")
    print(f"Transfer/ignored total: {money(debug_report['transfer_ignore_total'])}")
    print(f"Review/unknown total: {money(debug_report['review_unknown_total'])}")

    print(f"Coffee shops total: {money(debug_report['coffee_shops_total'])}")
    print(f"Groceries total: {money(debug_report['groceries_total'])}")
    print(f"Fast food total: {money(debug_report['fast_food_total'])}")
    print(f"Restaurants total: {money(debug_report['restaurants_total'])}")
    print(f"Total food: {money(debug_report['total_food'])}")

    print(f"LOC draws detected: {debug_report['loc_draws_detected']}")
    print(f"Credit card payments detected: {debug_report['credit_card_payments_detected']}")
    print(f"Transactions needing review: {debug_report['transactions_needing_review']}")

    print("\nTop 20 merchants by spend")
    for item in debug_report["top_merchants_by_total_spend"]:
        print(f"  - {item['label']}: {money(item['total_spend'])}")
    if not debug_report["top_merchants_by_total_spend"]:
        print("  (none)")

    print("\nTop 20 raw descriptions by frequency")
    for item in debug_report["top_raw_descriptions_by_frequency"]:
        print(f"  - {item['raw_description']}: {item['frequency']}")
    if not debug_report["top_raw_descriptions_by_frequency"]:
        print("  (none)")

    print("\nTransactions needing review")
    for item in debug_report["transactions_needing_review_details"]:
        amount = money(item["amount"])
        print(
            f"  - {item['transaction_date']} | {item['description']} | {amount} | "
            f"class={item['transaction_class']} | category={item['category_name'] or '--'}"
        )
    if not debug_report["transactions_needing_review_details"]:
        print("  (none)")


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    temp_dir = None
    if args.db:
        db_path = Path(args.db).expanduser().resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="moneyview-real-csv-")
        db_path = Path(temp_dir.name) / "moneyview.sqlite3"

    app = create_app({"DATABASE_PATH": db_path, "TESTING": True})

    try:
        with app.app_context():
            database = get_db()
            account_id, _ = resolve_account_id(database, args.account)
            profile_id, _ = resolve_profile_id(database, args.profile)
            report = import_csv(
                database=database,
                file_bytes=csv_path.read_bytes(),
                source_file_name=csv_path.name,
                account_id=account_id,
                profile_id=profile_id,
            )
            print_debug_report(csv_path, report["debug_report"])
            print(f"\nLocal validation DB: {db_path}")
    finally:
        if temp_dir and not args.keep_db:
            temp_dir.cleanup()


if __name__ == "__main__":
    main()
