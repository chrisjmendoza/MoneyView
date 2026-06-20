from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from .db import get_db
from .services.categorization_service import create_rule_from_review
from .services.constants import TRANSACTION_CLASSES
from .services.dashboard_service import build_dashboard
from .services.import_service import decode_upload, encode_upload, import_csv, normalize_merchant, preview_import


bp = Blueprint("moneyview", __name__)


@bp.get("/")
def dashboard() -> str:
    window = request.args.get("window", "current_pay_period")
    return render_template("dashboard.html", dashboard=build_dashboard(get_db(), window=window))


@bp.post("/balances")
def save_balance() -> str:
    database = get_db()
    database.execute(
        """
        insert into balance_snapshots (id, account_id, snapshot_date, balance, notes)
        values (?, ?, ?, ?, ?)
        """,
        (
            f"balance-{abs(hash((request.form['account_id'], request.form['snapshot_date'], request.form['balance'])))}",
            request.form["account_id"],
            request.form["snapshot_date"],
            request.form["balance"],
            request.form.get("notes"),
        ),
    )
    database.commit()
    return redirect(url_for("moneyview.dashboard"))


@bp.post("/settings")
def save_settings() -> str:
    database = get_db()
    for setting_key in (
        "pay_frequency",
        "normal_paycheck_amount",
        "payday_anchor",
        "checking_floor",
        "manual_bills_due_before_next_paycheck",
    ):
        database.execute(
            """
            insert into user_settings (id, setting_key, setting_value, notes)
            values (?, ?, ?, ?)
            on conflict(setting_key) do update set setting_value = excluded.setting_value, updated_at = current_timestamp
            """,
            (f"setting-{setting_key}", setting_key, request.form[setting_key], "Updated from dashboard."),
        )
    database.commit()
    return redirect(url_for("moneyview.dashboard"))


@bp.post("/bills")
def create_bill() -> str:
    database = get_db()
    database.execute(
        """
        insert into recurring_bills (
          id, name, expected_amount, due_day, frequency, category_id, account_id, is_shared, split_count, active, notes
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            f"bill-{abs(hash((request.form['name'], request.form['due_day'], request.form['expected_amount'])))}",
            request.form["name"],
            request.form["expected_amount"],
            request.form["due_day"],
            request.form["frequency"],
            request.form.get("category_id") or None,
            request.form.get("account_id") or None,
            1 if request.form.get("is_shared") else 0,
            request.form.get("split_count") or None,
            request.form.get("notes"),
        ),
    )
    database.commit()
    return redirect(url_for("moneyview.dashboard"))


@bp.post("/contacts")
def create_contact() -> str:
    database = get_db()
    database.execute(
        """
        insert into contacts (id, name, relationship_type, default_category_id, auto_apply, active, notes)
        values (?, ?, ?, ?, ?, 1, ?)
        """,
        (
            f"contact-{abs(hash((request.form['name'], request.form['relationship_type'], request.form.get('default_category_id') or '')))}",
            request.form["name"].strip(),
            request.form["relationship_type"],
            request.form.get("default_category_id") or None,
            1 if request.form.get("auto_apply") else 0,
            request.form.get("notes") or None,
        ),
    )
    database.commit()
    return redirect(url_for("moneyview.dashboard"))


@bp.route("/import", methods=["GET", "POST"])
def import_transactions() -> str:
    database = get_db()
    accounts = database.execute("select * from accounts where active = 1 order by name asc").fetchall()
    profiles = database.execute("select * from import_profiles where active = 1 order by institution asc, name asc").fetchall()
    preview_rows: list[dict] = []
    report = None
    form_state = {
        "account_id": request.form.get("account_id", ""),
        "profile_id": request.form.get("profile_id", ""),
        "source_file_name": request.form.get("source_file_name", ""),
        "file_payload": request.form.get("file_payload", ""),
    }
    selected_account = None
    selected_profile = None
    form_error = None

    if request.method == "POST":
        action = request.form.get("action")
        account_id = request.form["account_id"]
        profile_id = request.form["profile_id"]
        selected_account = next((account for account in accounts if account["id"] == account_id), None)
        selected_profile = next((profile for profile in profiles if profile["id"] == profile_id), None)
        try:
            if action == "preview":
                uploaded_file = request.files["csv_file"]
                file_bytes = uploaded_file.read()
                form_state["source_file_name"] = uploaded_file.filename or "upload.csv"
                form_state["file_payload"] = encode_upload(file_bytes)
                preview_rows = preview_import(database, file_bytes, account_id, profile_id)

            elif action == "import":
                file_bytes = decode_upload(request.form["file_payload"])
                preview_rows = preview_import(database, file_bytes, account_id, profile_id)
                report = import_csv(database, file_bytes, request.form["source_file_name"], account_id, profile_id)
        except ValueError as exc:
            form_error = str(exc)

    return render_template(
        "import.html",
        accounts=accounts,
        profiles=profiles,
        preview_rows=preview_rows,
        report=report,
        form_state=form_state,
        selected_account=selected_account,
        selected_profile=selected_profile,
        form_error=form_error,
    )


@bp.get("/review")
def review_queue() -> str:
    database = get_db()
    account_id = request.args.get("account_id", "")
    transaction_class = request.args.get("transaction_class", "")
    search = request.args.get("search", "").strip()
    only_zelle = request.args.get("only_zelle") == "1"
    limit = min(max(int(request.args.get("limit", 25) or 25), 1), 100)

    where_clauses = ["(transactions.needs_review = 1 or transactions.category_id is null)"]
    params: list = []

    if account_id:
        where_clauses.append("transactions.account_id = ?")
        params.append(account_id)
    if transaction_class:
        where_clauses.append("transactions.transaction_class = ?")
        params.append(transaction_class)
    if search:
        where_clauses.append("upper(transactions.description) like ?")
        params.append(f"%{search.upper()}%")
    if only_zelle:
        where_clauses.append("upper(transactions.description) like '%ZELLE%'")

    where_sql = " and ".join(where_clauses)

    total_review_count = database.execute(
        f"""
        select count(*) as review_count
        from transactions
        where {where_sql}
        """,
        params,
    ).fetchone()["review_count"]

    transactions = database.execute(
        f"""
        select transactions.*, categories.name as category_name, accounts.name as account_name,
               case when upper(transactions.description) like '%ZELLE%' then 1 else 0 end as is_zelle
        from transactions
        left join categories on categories.id = transactions.category_id
        left join accounts on accounts.id = transactions.account_id
        where {where_sql}
        order by is_zelle desc, abs(transactions.amount) desc, transactions.transaction_date desc, transactions.created_at desc
        limit ?
        """,
        [*params, limit],
    ).fetchall()
    accounts = database.execute("select * from accounts where active = 1 order by name asc").fetchall()
    categories = database.execute("select * from categories where active = 1 order by name asc").fetchall()
    return render_template(
        "review_queue.html",
        transactions=transactions,
        accounts=accounts,
        categories=categories,
        transaction_classes=sorted(TRANSACTION_CLASSES),
        filter_state={
            "account_id": account_id,
            "transaction_class": transaction_class,
            "search": search,
            "only_zelle": only_zelle,
            "limit": limit,
        },
        review_count=total_review_count,
        shown_count=len(transactions),
    )


@bp.post("/review/<transaction_id>")
def update_review(transaction_id: str) -> str:
    database = get_db()
    category_id = request.form.get("category_id") or None
    transaction_class = request.form["transaction_class"]
    review_note = request.form.get("review_note") or None

    if transaction_class in {"ignore", "transfer"} and not category_id:
        category_id = "category-transfers-ignore"

    database.execute(
        """
        update transactions
        set category_id = ?,
            transaction_class = ?,
            needs_review = 0,
            review_note = ?,
            updated_at = current_timestamp
        where id = ?
        """,
        (category_id, transaction_class, review_note, transaction_id),
    )

    if request.form.get("create_rule"):
        rule_mode = request.form.get("rule_pattern_mode", "contains_merchant")
        base_description = request.form["rule_source_description"]
        merchant_guess = normalize_merchant(base_description)
        if rule_mode == "exact_description":
            pattern = base_description
            match_type = "exact"
        elif rule_mode == "custom_pattern":
            pattern = request.form["rule_pattern"]
            match_type = request.form["rule_match_type"]
        else:
            pattern = merchant_guess
            match_type = "contains"

        create_rule_from_review(
            database=database,
            pattern=pattern,
            match_type=match_type,
            category_id=category_id,
            transaction_class=transaction_class,
            priority=int(request.form.get("rule_priority") or 1000),
            notes=f"Created from review for transaction {transaction_id}.",
        )

    database.commit()
    redirect_params = {
        "account_id": request.form.get("next_account_id", ""),
        "transaction_class": request.form.get("next_transaction_class", ""),
        "search": request.form.get("next_search", ""),
        "limit": request.form.get("next_limit", "25"),
    }
    if request.form.get("next_only_zelle") == "1":
        redirect_params["only_zelle"] = "1"
    return redirect(url_for("moneyview.review_queue", **redirect_params))