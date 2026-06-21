from datetime import date
import re
import uuid

import csv
import io
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from .db import get_db
from .services.categorization_service import create_rule_from_review
from .services.constants import TRANSACTION_CLASSES
from .services.dashboard_service import build_dashboard
from .services.import_service import decode_upload, encode_upload, import_csv, normalize_merchant, preview_import


bp = Blueprint("moneyview", __name__)


def _coerce_positive_int(raw_value: str | None, default: int, *, max_value: int | None = None) -> int:
    try:
        value = int(raw_value or default)
    except (TypeError, ValueError):
        value = default

    value = max(value, 1)
    if max_value is not None:
        value = min(value, max_value)
    return value


def _read_review_filter_state(source) -> dict:
    raw_scroll_y = (source.get("scroll_y", "") or source.get("next_scroll_y", "")).strip()
    return {
        "account_id": source.get("account_id", ""),
        "transaction_class": source.get("transaction_class", ""),
        "search": source.get("search", "").strip(),
        "only_zelle": source.get("only_zelle") == "1",
        "limit": _coerce_positive_int(source.get("limit"), 25, max_value=100),
        "page": _coerce_positive_int(source.get("page"), 1),
        "scroll_y": raw_scroll_y if raw_scroll_y.isdigit() else "",
    }


def _build_review_query_parts(filter_state: dict) -> tuple[str, list]:
    where_clauses = ["(transactions.needs_review = 1 or transactions.category_id is null)"]
    params: list = []

    if filter_state["account_id"]:
        where_clauses.append("transactions.account_id = ?")
        params.append(filter_state["account_id"])
    if filter_state["transaction_class"]:
        where_clauses.append("transactions.transaction_class = ?")
        params.append(filter_state["transaction_class"])
    if filter_state["search"]:
        where_clauses.append("upper(transactions.description) like ?")
        params.append(f"%{filter_state['search'].upper()}%")
    if filter_state["only_zelle"]:
        where_clauses.append("upper(transactions.description) like '%ZELLE%'")

    return " and ".join(where_clauses), params


def _build_review_redirect_params(filter_state: dict) -> dict:
    redirect_params = {
        "account_id": filter_state["account_id"],
        "transaction_class": filter_state["transaction_class"],
        "search": filter_state["search"],
        "limit": filter_state["limit"],
        "page": filter_state["page"],
    }
    if filter_state["only_zelle"]:
        redirect_params["only_zelle"] = "1"
    if filter_state.get("scroll_y"):
        redirect_params["scroll_y"] = filter_state["scroll_y"]
    return redirect_params


def _apply_rule_to_existing_queue(
    database,
    pattern: str,
    match_type: str,
    category_id: str | None,
    transaction_class: str,
    exclude_id: str,
) -> int:
    base_where = "(needs_review = 1 or category_id is null) and id != ?"
    base_params: list = [exclude_id]

    if match_type == "contains":
        where = f"{base_where} and upper(description) like ?"
        params = [*base_params, f"%{pattern.upper()}%"]
        database.execute(
            f"""
            update transactions
            set category_id = ?, transaction_class = ?, needs_review = 0,
                review_note = 'Auto-applied from matching rule.', updated_at = current_timestamp
            where {where}
            """,
            [category_id, transaction_class, *params],
        )
        return database.execute(f"select changes() as n").fetchone()["n"]

    if match_type == "exact":
        where = f"{base_where} and upper(description) = ?"
        params = [*base_params, pattern.upper()]
        database.execute(
            f"""
            update transactions
            set category_id = ?, transaction_class = ?, needs_review = 0,
                review_note = 'Auto-applied from matching rule.', updated_at = current_timestamp
            where {where}
            """,
            [category_id, transaction_class, *params],
        )
        return database.execute("select changes() as n").fetchone()["n"]

    if match_type == "regex":
        import re as _re
        candidates = database.execute(
            "select id, description from transactions where needs_review = 1 or category_id is null"
        ).fetchall()
        matched_ids = [
            row["id"]
            for row in candidates
            if row["id"] != exclude_id and _re.search(pattern, row["description"] or "", _re.IGNORECASE)
        ]
        for txn_id in matched_ids:
            database.execute(
                """
                update transactions
                set category_id = ?, transaction_class = ?, needs_review = 0,
                    review_note = 'Auto-applied from matching rule.', updated_at = current_timestamp
                where id = ?
                """,
                [category_id, transaction_class, txn_id],
            )
        return len(matched_ids)

    return 0


def _slugify_category_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "custom"


def _create_or_reuse_category(database, raw_name: str) -> str | None:
    category_name = (raw_name or "").strip()
    if not category_name:
        return None

    existing = database.execute(
        "select id from categories where lower(name) = lower(?) limit 1",
        (category_name,),
    ).fetchone()
    if existing:
        database.execute(
            "update categories set active = 1, updated_at = current_timestamp where id = ?",
            (existing["id"],),
        )
        return existing["id"]

    base_slug = _slugify_category_name(category_name)
    candidate_id = f"category-user-{base_slug}"
    suffix = 2
    while database.execute("select 1 from categories where id = ?", (candidate_id,)).fetchone():
        candidate_id = f"category-user-{base_slug}-{suffix}"
        suffix += 1

    database.execute(
        """
        insert into categories (id, name, active, notes)
        values (?, ?, 1, ?)
        """,
        (candidate_id, category_name, "Created from review queue."),
    )
    return candidate_id


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
            f"balance-{uuid.uuid4().hex}",
            request.form["account_id"],
            request.form["snapshot_date"],
            request.form["balance"],
            request.form.get("notes"),
        ),
    )
    database.commit()
    flash("Balance saved.", "success")
    return redirect(url_for("moneyview.dashboard"))


@bp.post("/settings")
def save_settings() -> str:
    # Validate before touching the DB
    try:
        _date.fromisoformat(request.form["payday_anchor"])
    except (ValueError, KeyError):
        flash("Payday Anchor must be a valid date in YYYY-MM-DD format.", "error")
        return redirect(url_for("moneyview.dashboard"))
    for decimal_key in ("normal_paycheck_amount", "checking_floor", "manual_bills_due_before_next_paycheck"):
        try:
            Decimal(request.form.get(decimal_key, "0"))
        except InvalidOperation:
            flash(f"'{decimal_key}' must be a number.", "error")
            return redirect(url_for("moneyview.dashboard"))

    database = get_db()
    for setting_key in (
        "pay_frequency",
        "normal_paycheck_amount",
        "payday_anchor",
        "checking_floor",
        "manual_bills_due_before_next_paycheck",
        "payroll_description_hint",
    ):
        database.execute(
            """
            insert into user_settings (id, setting_key, setting_value, notes)
            values (?, ?, ?, ?)
            on conflict(setting_key) do update set setting_value = excluded.setting_value, updated_at = current_timestamp
            """,
            (f"setting-{setting_key}", setting_key, request.form.get(setting_key, ""), "Updated from dashboard."),
        )
    database.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("moneyview.dashboard"))


@bp.post("/bills")
def create_bill() -> str:
    database = get_db()
    database.execute(
        """
        insert into recurring_bills (
          id, name, expected_amount, due_day, due_month, frequency, category_id, account_id, is_shared, split_count, active, notes
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            f"bill-{uuid.uuid4().hex}",
            request.form["name"],
            request.form["expected_amount"],
            request.form["due_day"],
            request.form.get("due_month") or None,
            request.form["frequency"],
            request.form.get("category_id") or None,
            request.form.get("account_id") or None,
            1 if request.form.get("is_shared") else 0,
            request.form.get("split_count") or None,
            request.form.get("notes"),
        ),
    )
    database.commit()
    flash(f"Bill \"{request.form['name']}\" added.", "success")
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
            f"contact-{uuid.uuid4().hex}",
            request.form["name"].strip(),
            request.form["relationship_type"],
            request.form.get("default_category_id") or None,
            1 if request.form.get("auto_apply") else 0,
            request.form.get("notes") or None,
        ),
    )
    database.commit()
    flash(f"Contact \"{request.form['name'].strip()}\" added.", "success")
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


@bp.get("/bills")
def bills_list() -> str:
    database = get_db()
    bills = database.execute(
        """
        select recurring_bills.*, categories.name as category_name, accounts.name as account_name
        from recurring_bills
        left join categories on categories.id = recurring_bills.category_id
        left join accounts on accounts.id = recurring_bills.account_id
        order by recurring_bills.due_day asc, recurring_bills.name asc
        """
    ).fetchall()
    categories = database.execute("select * from categories where active = 1 order by name asc").fetchall()
    accounts = database.execute("select * from accounts where active = 1 order by name asc").fetchall()
    return render_template("bills.html", bills=bills, categories=categories, accounts=accounts)


@bp.post("/bills/<bill_id>/edit")
def edit_bill(bill_id: str) -> str:
    database = get_db()
    database.execute(
        """
        update recurring_bills
        set name = ?,
            expected_amount = ?,
            due_day = ?,
            due_month = ?,
            frequency = ?,
            category_id = ?,
            account_id = ?,
            is_shared = ?,
            split_count = ?,
            active = ?,
            notes = ?,
            updated_at = current_timestamp
        where id = ?
        """,
        (
            request.form["name"],
            request.form["expected_amount"],
            request.form["due_day"],
            request.form.get("due_month") or None,
            request.form["frequency"],
            request.form.get("category_id") or None,
            request.form.get("account_id") or None,
            1 if request.form.get("is_shared") else 0,
            request.form.get("split_count") or None,
            1 if request.form.get("active") else 0,
            request.form.get("notes") or None,
            bill_id,
        ),
    )
    database.commit()
    flash(f"Bill \"{request.form['name']}\" updated.", "success")
    return redirect(url_for("moneyview.bills_list"))


@bp.post("/bills/<bill_id>/delete")
def delete_bill(bill_id: str) -> str:
    database = get_db()
    row = database.execute("select name from recurring_bills where id = ?", (bill_id,)).fetchone()
    database.execute("delete from recurring_bills where id = ?", (bill_id,))
    database.commit()
    flash(f"Bill \"{row['name'] if row else bill_id}\" deleted.", "success")
    return redirect(url_for("moneyview.bills_list"))


@bp.get("/transactions")
def transactions_list() -> str:
    database = get_db()

    account_id = request.args.get("account_id", "")
    transaction_class = request.args.get("transaction_class", "")
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    limit = _coerce_positive_int(request.args.get("limit"), 50, max_value=200)
    page = _coerce_positive_int(request.args.get("page"), 1)

    where_clauses = ["1=1"]
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
    if category_id == "__uncategorized__":
        where_clauses.append("transactions.category_id is null")
    elif category_id:
        where_clauses.append("transactions.category_id = ?")
        params.append(category_id)
    if date_from:
        where_clauses.append("transactions.transaction_date >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("transactions.transaction_date <= ?")
        params.append(date_to)

    where_sql = " and ".join(where_clauses)

    total_count = database.execute(
        f"select count(*) as cnt from transactions where {where_sql}", params
    ).fetchone()["cnt"]

    total_pages = max((total_count - 1) // limit + 1, 1)
    page = min(page, total_pages)
    offset = (page - 1) * limit

    transactions = database.execute(
        f"""
        select transactions.*, categories.name as category_name, accounts.name as account_name
        from transactions
        left join categories on categories.id = transactions.category_id
        left join accounts on accounts.id = transactions.account_id
        where {where_sql}
        order by transactions.transaction_date desc, transactions.created_at desc
        limit ? offset ?
        """,
        [*params, limit, offset],
    ).fetchall()

    accounts = database.execute("select * from accounts where active = 1 order by name asc").fetchall()
    categories = database.execute("select * from categories where active = 1 order by name asc").fetchall()

    filter_state = {
        "account_id": account_id,
        "transaction_class": transaction_class,
        "search": search,
        "category_id": category_id,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
        "page": page,
    }

    return render_template(
        "transactions.html",
        transactions=transactions,
        accounts=accounts,
        categories=categories,
        transaction_classes=sorted(TRANSACTION_CLASSES),
        filter_state=filter_state,
        total_count=total_count,
        shown_start=offset + 1 if total_count else 0,
        shown_end=min(offset + len(transactions), total_count),
        pagination={
            "current_page": page,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_page": page - 1,
            "next_page": page + 1,
        },
    )


@bp.get("/transactions/export")
def export_transactions() -> Response:
    database = get_db()

    account_id = request.args.get("account_id", "")
    transaction_class = request.args.get("transaction_class", "")
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    where_clauses = ["1=1"]
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
    if category_id == "__uncategorized__":
        where_clauses.append("transactions.category_id is null")
    elif category_id:
        where_clauses.append("transactions.category_id = ?")
        params.append(category_id)
    if date_from:
        where_clauses.append("transactions.transaction_date >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("transactions.transaction_date <= ?")
        params.append(date_to)

    where_sql = " and ".join(where_clauses)
    rows = database.execute(
        f"""
        select transactions.transaction_date, transactions.description,
               transactions.amount, transactions.transaction_class,
               categories.name as category_name, accounts.name as account_name,
               transactions.review_note, transactions.needs_review
        from transactions
        left join categories on categories.id = transactions.category_id
        left join accounts on accounts.id = transactions.account_id
        where {where_sql}
        order by transactions.transaction_date desc, transactions.created_at desc
        """,
        params,
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Description", "Amount", "Class", "Category", "Account", "Review Note", "Needs Review"])
    for row in rows:
        writer.writerow([
            row["transaction_date"],
            row["description"],
            row["amount"],
            row["transaction_class"],
            row["category_name"] or "",
            row["account_name"] or "",
            row["review_note"] or "",
            "yes" if row["needs_review"] else "no",
        ])

    filename = f"moneyview-export-{_date.today().isoformat()}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.post("/transactions/<transaction_id>/edit")
def edit_transaction(transaction_id: str) -> str:
    database = get_db()
    category_id = request.form.get("category_id") or None
    new_category_name = request.form.get("new_category_name", "")
    transaction_class = request.form["transaction_class"]
    review_note = request.form.get("review_note") or None

    if transaction_class in {"ignore", "transfer"} and not category_id:
        category_id = "category-transfers-ignore"

    if new_category_name.strip():
        category_id = _create_or_reuse_category(database, new_category_name)

    needs_review = 1 if request.form.get("needs_review") else 0

    database.execute(
        """
        update transactions
        set category_id = ?,
            transaction_class = ?,
            needs_review = ?,
            review_note = ?,
            updated_at = current_timestamp
        where id = ?
        """,
        (category_id, transaction_class, needs_review, review_note, transaction_id),
    )
    database.commit()
    flash("Transaction updated.", "success")

    redirect_params = {k: v for k, v in {
        "account_id": request.form.get("next_account_id", ""),
        "transaction_class": request.form.get("next_transaction_class", ""),
        "search": request.form.get("next_search", ""),
        "category_id": request.form.get("next_category_id", ""),
        "date_from": request.form.get("next_date_from", ""),
        "date_to": request.form.get("next_date_to", ""),
        "limit": request.form.get("next_limit", "50"),
        "page": request.form.get("next_page", "1"),
    }.items() if v}
    return redirect(url_for("moneyview.transactions_list", **redirect_params))


@bp.get("/rules")
def rules_list() -> str:
    database = get_db()
    rules = database.execute(
        """
        select
          categorization_rules.*,
          categories.name as category_name
        from categorization_rules
        left join categories on categories.id = categorization_rules.category_id
        order by categorization_rules.priority desc, categorization_rules.updated_at desc, categorization_rules.id asc
        """
    ).fetchall()
    categories = database.execute("select * from categories where active = 1 order by name asc").fetchall()
    return render_template(
        "rules.html",
        rules=rules,
        categories=categories,
        transaction_classes=sorted(TRANSACTION_CLASSES),
    )


@bp.post("/rules/<rule_id>/toggle")
def toggle_rule(rule_id: str) -> str:
    database = get_db()
    row = database.execute("select active from categorization_rules where id = ?", (rule_id,)).fetchone()
    if row:
        new_active = 0 if row["active"] else 1
        database.execute(
            "update categorization_rules set active = ?, updated_at = current_timestamp where id = ?",
            (new_active, rule_id),
        )
        database.commit()
        state = "enabled" if new_active else "disabled"
        flash(f"Rule {state}.", "success")
    return redirect(url_for("moneyview.rules_list"))


@bp.post("/rules/<rule_id>/edit")
def edit_rule(rule_id: str) -> str:
    database = get_db()
    database.execute(
        """
        update categorization_rules
        set pattern = ?,
            match_type = ?,
            category_id = ?,
            transaction_class = ?,
            priority = ?,
            notes = ?,
            updated_at = current_timestamp
        where id = ?
        """,
        (
            request.form["pattern"],
            request.form["match_type"],
            request.form.get("category_id") or None,
            request.form["transaction_class"],
            int(request.form.get("priority") or 1000),
            request.form.get("notes") or None,
            rule_id,
        ),
    )
    database.commit()
    flash("Rule updated.", "success")
    return redirect(url_for("moneyview.rules_list"))


@bp.post("/rules/<rule_id>/delete")
def delete_rule(rule_id: str) -> str:
    database = get_db()
    database.execute("delete from categorization_rules where id = ?", (rule_id,))
    database.commit()
    flash("Rule deleted.", "success")
    return redirect(url_for("moneyview.rules_list"))


@bp.get("/review")
def review_queue() -> str:
    database = get_db()
    filter_state = _read_review_filter_state(request.args)
    raw_scroll_y = request.args.get("scroll_y", "").strip()
    restored_scroll_y = raw_scroll_y if raw_scroll_y.isdigit() else ""
    where_sql, params = _build_review_query_parts(filter_state)

    total_review_count = database.execute(
        f"""
        select count(*) as review_count
        from transactions
        where {where_sql}
        """,
        params,
    ).fetchone()["review_count"]

    total_pages = max((total_review_count - 1) // filter_state["limit"] + 1, 1)
    filter_state["page"] = min(filter_state["page"], total_pages)
    offset = (filter_state["page"] - 1) * filter_state["limit"]

    transactions = database.execute(
        f"""
        select transactions.*, categories.name as category_name, accounts.name as account_name,
               case when upper(transactions.description) like '%ZELLE%' then 1 else 0 end as is_zelle
        from transactions
        left join categories on categories.id = transactions.category_id
        left join accounts on accounts.id = transactions.account_id
        where {where_sql}
        order by is_zelle desc, abs(transactions.amount) desc, transactions.transaction_date desc, transactions.created_at desc
        limit ? offset ?
        """,
        [*params, filter_state["limit"], offset],
    ).fetchall()
    accounts = database.execute("select * from accounts where active = 1 order by name asc").fetchall()
    categories = database.execute("select * from categories where active = 1 order by name asc").fetchall()

    shown_start = offset + 1 if total_review_count else 0
    shown_end = min(offset + len(transactions), total_review_count)
    return render_template(
        "review_queue.html",
        transactions=transactions,
        accounts=accounts,
        categories=categories,
        transaction_classes=sorted(TRANSACTION_CLASSES),
        filter_state=filter_state,
        review_count=total_review_count,
        shown_count=len(transactions),
        shown_start=shown_start,
        shown_end=shown_end,
        pagination={
            "current_page": filter_state["page"],
            "total_pages": total_pages,
            "has_previous": filter_state["page"] > 1,
            "has_next": filter_state["page"] < total_pages,
            "previous_page": filter_state["page"] - 1,
            "next_page": filter_state["page"] + 1,
        },
        restored_scroll_y=restored_scroll_y,
    )


@bp.post("/review/<transaction_id>")
def update_review(transaction_id: str) -> str:
    database = get_db()
    category_id = request.form.get("category_id") or None
    new_category_name = request.form.get("new_category_name", "")
    transaction_class = request.form["transaction_class"]
    review_note = request.form.get("review_note") or None
    filter_state = _read_review_filter_state(
        {
            "account_id": request.form.get("next_account_id", ""),
            "transaction_class": request.form.get("next_transaction_class", ""),
            "search": request.form.get("next_search", ""),
            "only_zelle": request.form.get("next_only_zelle", "0"),
            "limit": request.form.get("next_limit", "25"),
            "page": request.form.get("next_page", "1"),
            "scroll_y": request.form.get("next_scroll_y", ""),
        }
    )

    if transaction_class in {"ignore", "transfer"} and not category_id:
        category_id = "category-transfers-ignore"

    if new_category_name.strip():
        category_id = _create_or_reuse_category(database, new_category_name)

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

        backfill_count = 0
        if request.form.get("apply_to_matching"):
            backfill_count = _apply_rule_to_existing_queue(
                database, pattern, match_type, category_id, transaction_class, transaction_id
            )

    where_sql, params = _build_review_query_parts(filter_state)
    remaining_review_count = database.execute(
        f"""
        select count(*) as review_count
        from transactions
        where {where_sql}
        """,
        params,
    ).fetchone()["review_count"]

    database.commit()

    if request.form.get("create_rule"):
        backfill_msg = f" Also cleared {backfill_count} other matching transaction(s)." if backfill_count else ""
        flash(f"Transaction updated. Rule created.{backfill_msg}", "success")
    else:
        flash("Transaction updated.", "success")
    total_pages = max((remaining_review_count - 1) // filter_state["limit"] + 1, 1)
    filter_state["page"] = min(filter_state["page"], total_pages)
    return redirect(url_for("moneyview.review_queue", **_build_review_redirect_params(filter_state)))


# ── Import history + rollback ──────────────────────────────────────────────


@bp.get("/imports")
def imports_list() -> str:
    database = get_db()
    imports = database.execute(
        """
        select imports.*,
               accounts.name as account_name,
               import_profiles.name as profile_name
        from imports
        join accounts on accounts.id = imports.account_id
        join import_profiles on import_profiles.id = imports.import_profile_id
        order by imports.imported_at desc, imports.id desc
        """
    ).fetchall()
    return render_template("imports.html", imports=imports)


@bp.post("/imports/<import_id>/rollback")
def rollback_import(import_id: str) -> str:
    database = get_db()
    row = database.execute(
        "select source_file_name, new_transactions from imports where id = ?", (import_id,)
    ).fetchone()
    if not row:
        flash("Import not found.", "error")
        return redirect(url_for("moneyview.imports_list"))
    database.execute("delete from transactions where source_import_id = ?", (import_id,))
    deleted_count = database.execute("select changes() as n").fetchone()["n"]
    database.execute("delete from imports where id = ?", (import_id,))
    database.commit()
    flash(
        f"Rolled back import of '{row['source_file_name']}'. "
        f"{deleted_count} transaction(s) removed.",
        "success",
    )
    return redirect(url_for("moneyview.imports_list"))