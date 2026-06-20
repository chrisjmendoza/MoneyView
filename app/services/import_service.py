import base64
import csv
import hashlib
import io
import json
import re
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .categorization_service import apply_rules, fetch_rules
from .constants import ACCOUNT_TYPES, TRANSACTION_CLASSES


FEE_INTEREST_TOKENS = ("INTEREST", "FINANCE CHARGE", "ANNUAL FEE", "LATE FEE", "SERVICE FEE")
TRANSFER_TOKENS = ("TRANSFER", "XFER", "TRNSFR")
ZELLE_TOKENS = ("ZELLE FROM", "ZELLE TO", "ZELLE")


def encode_upload(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode("ascii")


def decode_upload(encoded_payload: str) -> bytes:
    return base64.b64decode(encoded_payload.encode("ascii"))


def get_account(database: sqlite3.Connection, account_id: str) -> dict:
    account = database.execute("select * from accounts where id = ?", (account_id,)).fetchone()
    if not account:
        raise ValueError("Unknown account selected.")
    return account


def get_profile(database: sqlite3.Connection, profile_id: str) -> dict:
    profile = database.execute("select * from import_profiles where id = ? and active = 1", (profile_id,)).fetchone()
    if not profile:
        raise ValueError("Unknown import profile selected.")
    return profile


def preview_import(database: sqlite3.Connection, file_bytes: bytes, account_id: str, profile_id: str, limit: int = 5) -> list[dict]:
    account = get_account(database, account_id)
    profile = get_profile(database, profile_id)
    rules = fetch_rules(database)
    contacts = fetch_contacts(database)
    preview_rows: list[dict] = []

    for index, row in enumerate(iter_csv_rows(file_bytes, profile), start=1):
        if not should_include_row_for_account(row, profile, account):
            continue
        normalized = normalize_row(row, profile, account)
        normalized = apply_rules(normalized, rules)
        normalized = apply_contextual_overrides(normalized, account, contacts)
        preview_rows.append(
            {
                "row_number": index,
                "transaction_date": normalized["transaction_date"],
                "posted_date": normalized["posted_date"],
                "description": normalized["description"],
                "merchant": normalized["merchant"],
                "amount": f"{normalized['amount']:.2f}",
                "direction": normalized["direction"],
                "account_name": account["name"],
                "transaction_hash": normalized["transaction_hash"],
                "matched_rule": normalized.get("matched_rule_pattern"),
                "transaction_class": normalized["transaction_class"],
                "category_name": normalized.get("category_name"),
                "needs_review": normalized["needs_review"],
            }
        )
        if len(preview_rows) >= limit:
            break

    return preview_rows


def import_csv(database: sqlite3.Connection, file_bytes: bytes, source_file_name: str, account_id: str, profile_id: str) -> dict:
    account = get_account(database, account_id)
    profile = get_profile(database, profile_id)
    rules = fetch_rules(database)
    contacts = fetch_contacts(database)
    import_id = f"import-{uuid.uuid4().hex}"

    database.execute(
        """
        insert into imports (id, account_id, import_profile_id, source_file_name)
        values (?, ?, ?, ?)
        """,
        (import_id, account_id, profile_id, source_file_name),
    )

    rows_read = 0
    new_transactions = 0
    duplicates_skipped = 0
    needs_review_count = 0
    errors: list[str] = []

    for index, row in enumerate(iter_csv_rows(file_bytes, profile), start=1):
        if not should_include_row_for_account(row, profile, account):
            continue
        rows_read += 1
        try:
            normalized = normalize_row(row, profile, account)
            normalized = apply_rules(normalized, rules)
            normalized = apply_contextual_overrides(normalized, account, contacts)
            normalized["source_import_id"] = import_id

            if normalized["needs_review"]:
                needs_review_count += 1

            inserted = insert_transaction(database, normalized)
            if inserted:
                new_transactions += 1
            else:
                duplicates_skipped += 1
        except Exception as exc:
            errors.append(f"Row {index}: {exc}")

    database.execute(
        """
        update imports
        set rows_read = ?,
            new_transactions = ?,
            duplicates_skipped = ?,
            errors_count = ?,
            needs_review_count = ?,
            error_summary = ?
        where id = ?
        """,
        (
            rows_read,
            new_transactions,
            duplicates_skipped,
            len(errors),
            needs_review_count,
            "\n".join(errors) if errors else None,
            import_id,
        ),
    )
    database.commit()

    debug_report = build_import_debug_report(database, import_id)

    return {
        "import_id": import_id,
        "rows_read": rows_read,
        "new_transactions": new_transactions,
        "duplicates_skipped": duplicates_skipped,
        "errors": errors,
        "needs_review_count": needs_review_count,
        "debug_report": debug_report,
    }


def iter_csv_rows(file_bytes: bytes, profile: dict):
    text = file_bytes.decode("utf-8-sig")
    stream = io.StringIO(text)

    if profile["has_header"]:
        reader = csv.DictReader(stream)
        for row in reader:
            yield row
        return

    reader = csv.reader(stream)
    for row in reader:
        yield {f"column_{index + 1}": value for index, value in enumerate(row)}


def normalize_row(row: dict, profile: dict, account: dict) -> dict:
    transaction_date = parse_date(value_for_column(row, profile["date_column"]), profile["date_format"])
    posted_date = None
    if profile["posted_date_column"]:
        posted_value = value_for_column(row, profile["posted_date_column"])
        posted_date = parse_date(posted_value, profile["date_format"]) if posted_value else None

    raw_description = value_for_column(row, profile["description_column"])
    description = " ".join(raw_description.split())
    merchant = normalize_merchant(description)
    amount = calculate_amount(row, profile)
    direction = "inflow" if amount > 0 else "outflow"
    transaction_class = infer_base_transaction_class(
        account_type=account["account_type"],
        amount=amount,
        description=description,
    )
    transaction_hash = build_transaction_hash(transaction_date, posted_date, account["id"], description, amount)

    normalized = {
        "id": f"txn-{transaction_hash[:18]}",
        "transaction_date": transaction_date.isoformat(),
        "posted_date": posted_date.isoformat() if posted_date else None,
        "account_id": account["id"],
        "description": description,
        "raw_description": raw_description,
        "merchant": merchant,
        "amount": amount,
        "direction": direction,
        "transaction_class": transaction_class,
        "category_id": None,
        "category_name": None,
        "needs_review": False,
        "review_note": None,
        "matched_rule_id": None,
        "matched_rule_pattern": None,
        "transaction_hash": transaction_hash,
        "raw_csv_row_json": json.dumps(row, sort_keys=True),
        "source_import_id": None,
    }
    return normalized


def normalize_merchant(description: str) -> str:
    text = (description or "").upper()
    prefixes = [
        "POS PURCHASE",
        "POS",
        "DEBIT CARD PURCHASE",
        "DEBIT PURCHASE",
        "DEBIT",
        "ACH DEBIT",
        "ACH CREDIT",
        "ONLINE TRANSFER",
        "ONLINE PAYMENT",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()

    text = re.sub(r"\b\d{2,}\b", "", text)
    text = re.sub(r"[#*]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    state_suffixes = [
        " WA",
        " OR",
        " CA",
    ]
    for suffix in state_suffixes:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()

    title = text.title()
    if not title:
        return "Unknown Merchant"
    return title


def infer_base_transaction_class(account_type: str, amount: Decimal, description: str) -> str:
    if account_type not in ACCOUNT_TYPES:
        raise ValueError(f"Unsupported account type: {account_type}")

    text = description.upper()

    if any(token in text for token in TRANSFER_TOKENS):
        return "transfer"

    if any(token in text for token in FEE_INTEREST_TOKENS):
        return "fee_interest"

    if account_type in {"line_of_credit", "loan"}:
        return "debt_draw" if amount > 0 else "debt_payment"

    if account_type == "credit_card":
        if amount < 0:
            return "expense"
        if any(token in text for token in ("PAYMENT", "PMT", "AUTOPAY", "ONLINE PAYMENT")):
            return "debt_payment"
        return "refund"

    if account_type in {"checking", "savings", "cash", "other"}:
        if amount < 0:
            if any(token in text for token in ("CREDIT CARD", "CC PAYMENT", "CARD PAYMENT", "LOC PAYMENT", "LOAN PAYMENT")):
                return "debt_payment"
            if any(token in text for token in ZELLE_TOKENS):
                return "needs_review"
            return "expense"
        if any(token in text for token in ZELLE_TOKENS):
            return "needs_review"
        if any(token in text for token in ("REIMBURSE", "ROOMMATE", "VENMO CASHOUT", "CASH APP")):
            return "reimbursement"
        if any(token in text for token in ("LOC ADVANCE", "LINE OF CREDIT", "LOAN DRAW")):
            return "debt_draw"
        return "income"

    return "needs_review"


def fetch_contacts(database: sqlite3.Connection) -> list[dict]:
    return database.execute(
        """
        select
          contacts.id,
          contacts.name,
          contacts.relationship_type,
          contacts.default_category_id,
          contacts.auto_apply,
          contacts.notes,
          categories.name as default_category_name
        from contacts
        left join categories on categories.id = contacts.default_category_id
        where contacts.active = 1
        order by contacts.name asc
        """
    ).fetchall()


def is_user_created_rule(rule_id: str | None) -> bool:
    return bool(rule_id and rule_id.startswith("rule-user-"))


def find_contact_match(description: str, contacts: list[dict]) -> dict | None:
    text = description.upper()
    for contact in contacts:
        contact_name = (contact.get("name") or "").strip().upper()
        if contact_name and contact_name in text:
            return contact
    return None


def default_transaction_class_for_category(category_name: str | None) -> str | None:
    if category_name == "Household Reimbursement":
        return "reimbursement"
    if category_name == "Credit Card Payment":
        return "debt_payment"
    if category_name == "LOC Draw":
        return "debt_draw"
    return None


def apply_loc_overrides(transaction: dict, account: dict) -> dict:
    if account["account_type"] not in {"line_of_credit", "loan"}:
        return transaction

    text = (transaction.get("description") or "").upper()
    if any(token in text for token in FEE_INTEREST_TOKENS):
        transaction["transaction_class"] = "fee_interest"
        transaction["needs_review"] = True
        transaction["review_note"] = transaction.get("review_note") or "Interest or finance charge detected on debt account."
        return transaction

    transaction["transaction_class"] = "debt_draw" if transaction["amount"] > 0 else "debt_payment"
    return transaction


def apply_zelle_overrides(transaction: dict, contacts: list[dict]) -> dict:
    text = (transaction.get("description") or "").upper()
    if not any(token in text for token in ZELLE_TOKENS):
        return transaction

    if is_user_created_rule(transaction.get("matched_rule_id")):
        return transaction

    matched_contact = find_contact_match(transaction.get("description") or "", contacts)
    transaction["needs_review"] = True

    if "ZELLE FROM" in text and matched_contact:
        suggestion = matched_contact.get("default_category_name") or "Needs Review"
        if matched_contact.get("auto_apply"):
            transaction["category_id"] = matched_contact.get("default_category_id")
            transaction["category_name"] = matched_contact.get("default_category_name")
            transaction["transaction_class"] = default_transaction_class_for_category(suggestion) or "needs_review"
        else:
            transaction["category_id"] = None
            transaction["category_name"] = None
            transaction["transaction_class"] = "needs_review"
        transaction["review_note"] = (
            f"Zelle from known {matched_contact['relationship_type']} '{matched_contact['name']}'. "
            f"Suggested category: {suggestion}. Review before confirming."
        )
        return transaction

    transaction["category_id"] = None
    transaction["category_name"] = None
    transaction["transaction_class"] = "needs_review"
    direction_text = "from" if "ZELLE FROM" in text else "to" if "ZELLE TO" in text else "transaction"
    transaction["review_note"] = transaction.get("review_note") or f"Ambiguous Zelle {direction_text}; review before categorizing."
    return transaction


def apply_contextual_overrides(transaction: dict, account: dict, contacts: list[dict]) -> dict:
    transaction = apply_loc_overrides(transaction, account)
    transaction = apply_zelle_overrides(transaction, contacts)
    return transaction


def value_for_column(row: dict, column_name: str) -> str:
    candidates = [candidate.strip().lower() for candidate in (column_name or "").split("|") if candidate.strip()]
    for candidate in candidates:
        for key, value in row.items():
            if key is None:
                continue
            if key.strip().lower() == candidate:
                return (value or "").strip()
    raise ValueError(f"Missing expected column: {column_name}")


def optional_value_for_column(row: dict, column_name: str | None) -> str | None:
    if not column_name:
        return None
    try:
        return value_for_column(row, column_name)
    except ValueError:
        return None


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def should_include_row_for_account(row: dict, profile: dict, account: dict) -> bool:
    source_account = optional_value_for_column(row, profile.get("account_column"))
    if not source_account:
        return True

    account_refs = [account.get("external_account_ref"), account.get("name")]
    normalized_source = normalize_text(source_account)
    return any(normalize_text(candidate) == normalized_source for candidate in account_refs if candidate)


def parse_date(raw_value: str, date_format: str):
    if not raw_value:
        raise ValueError("Missing transaction date.")
    raw_value = raw_value.strip()
    formats = [candidate.strip() for candidate in (date_format or "").split("|") if candidate.strip()]
    for candidate in formats:
        try:
            return datetime.strptime(raw_value, candidate).date()
        except ValueError:
            continue
    raise ValueError(f"time data {raw_value!r} does not match format {date_format!r}")


def parse_decimal(raw_value: str | None) -> Decimal:
    cleaned = (raw_value or "").strip().replace(",", "").replace("$", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    if cleaned == "":
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount value: {raw_value}") from exc


def calculate_amount(row: dict, profile: dict) -> Decimal:
    sign_rule = profile["amount_sign_rule"]

    if sign_rule == "signed_amount":
        return parse_decimal(value_for_column(row, profile["amount_column"]))

    if sign_rule == "signed_amount_or_type_column":
        source_amount = parse_decimal(value_for_column(row, profile["amount_column"]))
        type_value = optional_value_for_column(row, profile.get("type_column"))
        if not type_value:
            return source_amount

        normalized_type = type_value.strip().lower()
        if normalized_type == "credit":
            return abs(source_amount)
        if normalized_type == "debit":
            return abs(source_amount) * Decimal("-1")
        return source_amount

    if sign_rule == "debit_credit_columns":
        credit = parse_decimal(value_for_column(row, profile["credit_column"]))
        debit = parse_decimal(value_for_column(row, profile["debit_column"]))
        return credit - debit

    source_amount = parse_decimal(value_for_column(row, profile["amount_column"]))

    if sign_rule == "credit_card_positive_purchases":
        return source_amount * Decimal("-1")

    if sign_rule == "credit_card_negative_purchases":
        return source_amount

    raise ValueError(f"Unsupported amount sign rule: {sign_rule}")


def build_transaction_hash(transaction_date, posted_date, account_id: str, description: str, amount: Decimal) -> str:
    payload = "|".join(
        [
            transaction_date.isoformat(),
            posted_date.isoformat() if posted_date else "",
            account_id,
            description.upper(),
            f"{amount:.2f}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def insert_transaction(database: sqlite3.Connection, normalized: dict) -> bool:
    existing = database.execute(
        "select id from transactions where account_id = ? and transaction_hash = ?",
        (normalized["account_id"], normalized["transaction_hash"]),
    ).fetchone()
    if existing:
        return False

    database.execute(
        """
        insert into transactions (
          id, transaction_date, posted_date, account_id, description, raw_description,
          merchant, amount, direction, transaction_class, category_id, needs_review, review_note,
          matched_rule_id, matched_rule_pattern,
          transaction_hash, raw_csv_row_json, source_import_id
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            normalized["id"],
            normalized["transaction_date"],
            normalized["posted_date"],
            normalized["account_id"],
            normalized["description"],
            normalized["raw_description"],
            normalized["merchant"],
            float(normalized["amount"]),
            normalized["direction"],
            normalize_transaction_class(normalized["transaction_class"]),
            normalized["category_id"],
            int(normalized["needs_review"]),
            normalized["review_note"],
            normalized.get("matched_rule_id"),
            normalized.get("matched_rule_pattern"),
            normalized["transaction_hash"],
            normalized["raw_csv_row_json"],
            normalized["source_import_id"],
        ),
    )
    return True


def normalize_transaction_class(transaction_class: str) -> str:
    if transaction_class not in TRANSACTION_CLASSES:
        return "needs_review"
    return transaction_class


def build_import_debug_report(database: sqlite3.Connection, import_id: str) -> dict:
    metadata = database.execute(
        """
        select
          imports.id,
          imports.source_file_name,
          imports.rows_read,
          imports.new_transactions,
          imports.duplicates_skipped,
          imports.errors_count,
          imports.error_summary,
          imports.needs_review_count,
          accounts.name as account_name,
          import_profiles.name as profile_name
        from imports
        join accounts on accounts.id = imports.account_id
        join import_profiles on import_profiles.id = imports.import_profile_id
        where imports.id = ?
        """,
        (import_id,),
    ).fetchone()

    totals = database.execute(
        """
        select
          min(transaction_date) as start_date,
          max(transaction_date) as end_date,
          coalesce(sum(case when amount > 0 then amount else 0 end), 0) as inflow_total,
          coalesce(sum(case when amount < 0 then abs(amount) else 0 end), 0) as outflow_total,
          coalesce(sum(amount), 0) as net_total,
          count(*) as total_rows
        from transactions
        where source_import_id = ?
        """,
        (import_id,),
    ).fetchone()

    class_totals = database.execute(
        """
        select
          coalesce(sum(case when transaction_class = 'income' then amount else 0 end), 0) as normal_income_total,
          coalesce(sum(case when transaction_class = 'reimbursement' then amount else 0 end), 0) as reimbursement_total,
          coalesce(sum(case when transaction_class = 'debt_draw' then abs(amount) else 0 end), 0) as debt_draw_total,
          coalesce(sum(case when transaction_class = 'expense' and amount < 0 then abs(amount) else 0 end), 0) as normal_expense_total,
          coalesce(sum(case when transaction_class = 'debt_payment' then abs(amount) else 0 end), 0) as debt_payment_total,
          coalesce(sum(case when transaction_class in ('transfer', 'ignore') then abs(amount) else 0 end), 0) as transfer_ignore_total,
          coalesce(sum(case when needs_review = 1 or category_id is null or transaction_class = 'needs_review' then abs(amount) else 0 end), 0) as review_unknown_total
        from transactions
        where source_import_id = ?
        """,
        (import_id,),
    ).fetchone()

    food_totals = database.execute(
        """
        select
          coalesce(sum(case when categories.name = 'Coffee Shops' and transactions.transaction_class = 'expense' and transactions.amount < 0 then abs(transactions.amount) else 0 end), 0) as coffee_total,
          coalesce(sum(case when categories.name = 'Groceries' and transactions.transaction_class = 'expense' and transactions.amount < 0 then abs(transactions.amount) else 0 end), 0) as groceries_total,
          coalesce(sum(case when categories.name = 'Fast Food' and transactions.transaction_class = 'expense' and transactions.amount < 0 then abs(transactions.amount) else 0 end), 0) as fast_food_total,
          coalesce(sum(case when categories.name = 'Restaurants' and transactions.transaction_class = 'expense' and transactions.amount < 0 then abs(transactions.amount) else 0 end), 0) as restaurants_total
        from transactions
        left join categories on categories.id = transactions.category_id
        where transactions.source_import_id = ?
        """,
        (import_id,),
    ).fetchone()

    detection_counts = database.execute(
        """
        select
          sum(case when transaction_class = 'debt_draw' or upper(description) like '%LOC ADVANCE%' or upper(description) like '%LINE OF CREDIT%' or upper(description) like '%LOAN DRAW%' then 1 else 0 end) as loc_draws_detected,
          sum(case when transaction_class = 'debt_payment' and (lower(description) like '%credit card%' or lower(description) like '%cc payment%' or lower(description) like '%card payment%' or lower(description) like '%autopay%') then 1 else 0 end) as credit_card_payments_detected
        from transactions
        where source_import_id = ?
        """,
        (import_id,),
    ).fetchone()

    top_raw_descriptions = database.execute(
        """
        select raw_description, count(*) as frequency
        from transactions
        where source_import_id = ?
        group by raw_description
        order by frequency desc, raw_description asc
        limit 20
        """,
        (import_id,),
    ).fetchall()

    top_spend_merchants = database.execute(
        """
        select coalesce(merchant, description) as label,
               round(sum(abs(amount)), 2) as total_spend
        from transactions
        where source_import_id = ? and amount < 0
        group by coalesce(merchant, description)
        order by total_spend desc, label asc
        limit 20
        """,
        (import_id,),
    ).fetchall()

    review_transactions = database.execute(
        """
        select
          transactions.transaction_date,
          transactions.description,
          transactions.amount,
          transactions.transaction_class,
          categories.name as category_name,
          transactions.review_note
        from transactions
        left join categories on categories.id = transactions.category_id
        where transactions.source_import_id = ?
          and (transactions.needs_review = 1 or transactions.category_id is null or transactions.transaction_class = 'needs_review')
        order by transactions.transaction_date desc, transactions.created_at desc
        limit 20
        """,
        (import_id,),
    ).fetchall()

    food_total = (
        Decimal(str(food_totals["coffee_total"] or 0))
        + Decimal(str(food_totals["groceries_total"] or 0))
        + Decimal(str(food_totals["fast_food_total"] or 0))
        + Decimal(str(food_totals["restaurants_total"] or 0))
    )

    return {
        "imported_file_name": metadata["source_file_name"],
        "selected_account": metadata["account_name"],
        "selected_import_profile": metadata["profile_name"],
        "date_range_detected": {
            "start": totals["start_date"],
            "end": totals["end_date"],
        },
        "total_rows_read": metadata["rows_read"],
        "new_transactions_inserted": metadata["new_transactions"],
        "duplicates_skipped": metadata["duplicates_skipped"],
        "errors": {
            "count": metadata["errors_count"],
            "details": (metadata["error_summary"] or "").split("\n") if metadata["error_summary"] else [],
        },
        "inflow_total": totals["inflow_total"],
        "outflow_total": totals["outflow_total"],
        "net_total": totals["net_total"],
        "normal_income_total": class_totals["normal_income_total"],
        "reimbursement_total": class_totals["reimbursement_total"],
        "debt_draw_total": class_totals["debt_draw_total"],
        "normal_expense_total": class_totals["normal_expense_total"],
        "debt_payment_total": class_totals["debt_payment_total"],
        "transfer_ignore_total": class_totals["transfer_ignore_total"],
        "review_unknown_total": class_totals["review_unknown_total"],
        "coffee_shops_total": food_totals["coffee_total"],
        "groceries_total": food_totals["groceries_total"],
        "fast_food_total": food_totals["fast_food_total"],
        "restaurants_total": food_totals["restaurants_total"],
        "total_food": food_total,
        "loc_draws_detected": int(detection_counts["loc_draws_detected"] or 0),
        "credit_card_payments_detected": int(detection_counts["credit_card_payments_detected"] or 0),
        "transactions_needing_review": metadata["needs_review_count"],
        "transactions_needing_review_details": review_transactions,
        "top_raw_descriptions_by_frequency": top_raw_descriptions,
        "top_merchants_by_total_spend": top_spend_merchants,
    }