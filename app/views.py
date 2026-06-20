from datetime import date
import re

from flask import Blueprint, redirect, render_template, request, url_for

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
    return {
        "account_id": source.get("account_id", ""),
        "transaction_class": source.get("transaction_class", ""),
        "search": source.get("search", "").strip(),
        "only_zelle": source.get("only_zelle") == "1",
        "limit": _coerce_positive_int(source.get("limit"), 25, max_value=100),
        "page": _coerce_positive_int(source.get("page"), 1),
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
    return redirect_params


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
    filter_state = _read_review_filter_state(request.args)
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
    total_pages = max((remaining_review_count - 1) // filter_state["limit"] + 1, 1)
    filter_state["page"] = min(filter_state["page"], total_pages)
    return redirect(url_for("moneyview.review_queue", **_build_review_redirect_params(filter_state)))