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
    preview_rows: list[dict] = []

    for index, row in enumerate(iter_csv_rows(file_bytes, profile), start=1):
        normalized = normalize_row(row, profile, account)
        normalized = apply_rules(normalized, rules)
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
        rows_read += 1
        try:
            normalized = normalize_row(row, profile, account)
            normalized = apply_rules(normalized, rules)
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

    if any(token in text for token in ("TRANSFER", "XFER", "TRNSFR")):
        return "transfer"

    if any(token in text for token in ("INTEREST", "ANNUAL FEE", "LATE FEE", "SERVICE FEE")):
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
            return "expense"
        if any(token in text for token in ("REIMBURSE", "ROOMMATE", "ZELLE FROM", "VENMO CASHOUT", "CASH APP")):
            return "reimbursement"
        if any(token in text for token in ("LOC ADVANCE", "LINE OF CREDIT", "LOAN DRAW")):
            return "debt_draw"
        return "income"

    return "needs_review"


def value_for_column(row: dict, column_name: str) -> str:
    target = column_name.strip().lower()
    for key, value in row.items():
        if key is None:
            continue
        if key.strip().lower() == target:
            return (value or "").strip()
    raise ValueError(f"Missing expected column: {column_name}")


def parse_date(raw_value: str, date_format: str):
    if not raw_value:
        raise ValueError("Missing transaction date.")
    return datetime.strptime(raw_value.strip(), date_format).date()


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
        "transactions_needing_review": metadata["needs_review_count"],
        "top_raw_descriptions_by_frequency": top_raw_descriptions,
        "top_merchants_by_total_spend": top_spend_merchants,
    }