import re
import sqlite3
import uuid


def fetch_rules(database: sqlite3.Connection) -> list[dict]:
    return database.execute(
        """
        select
          categorization_rules.id,
          categorization_rules.pattern,
          categorization_rules.match_type,
          categorization_rules.category_id,
          categorization_rules.transaction_class,
          categorization_rules.priority,
          categorization_rules.requires_review,
          categorization_rules.notes,
          categories.name as category_name
        from categorization_rules
        left join categories on categories.id = categorization_rules.category_id
        where categorization_rules.active = 1
        order by categorization_rules.priority desc, categorization_rules.updated_at desc, categorization_rules.id asc
        """
    ).fetchall()


def apply_rules(transaction: dict, rules: list[dict]) -> dict:
    description = (transaction.get("description") or "").upper()
    transaction["matched_rule_id"] = None
    transaction["matched_rule_pattern"] = None

    for rule in rules:
        pattern = (rule["pattern"] or "").upper()
        matched = False

        if rule["match_type"] == "contains":
            matched = pattern in description
        elif rule["match_type"] == "exact":
            matched = pattern == description
        elif rule["match_type"] == "regex":
            matched = bool(re.search(rule["pattern"], transaction.get("description") or "", re.IGNORECASE))
        else:
            raise ValueError(f"Unsupported match type: {rule['match_type']}")

        if matched:
            transaction["matched_rule_id"] = rule["id"]
            transaction["matched_rule_pattern"] = rule["pattern"]
            if rule["category_id"]:
                transaction["category_id"] = rule["category_id"]
                transaction["category_name"] = rule["category_name"]
            if rule["transaction_class"]:
                transaction["transaction_class"] = rule["transaction_class"]
            if rule["requires_review"]:
                transaction["needs_review"] = True
                transaction["review_note"] = rule["notes"] or "Matched a review-required rule."
            return transaction

    if not transaction.get("category_id") and transaction.get("transaction_class") in {"transfer", "ignore"}:
        transaction["category_id"] = "category-transfers-ignore"
        transaction["category_name"] = "Transfers / Ignore"
        transaction["needs_review"] = False
        transaction["review_note"] = None
        return transaction

    if not transaction.get("category_id"):
        transaction["needs_review"] = True
        transaction.setdefault("review_note", "No categorization rule matched.")
        if transaction.get("transaction_class") not in {"needs_review", "ignore", "transfer"}:
            transaction["transaction_class"] = "needs_review"
    return transaction


def create_rule_from_review(
    database: sqlite3.Connection,
    pattern: str,
    match_type: str,
    category_id: str | None,
    transaction_class: str,
    priority: int = 1000,
    requires_review: bool = False,
    notes: str | None = None,
) -> None:
    rule_id = f"rule-user-{uuid.uuid4().hex[:12]}"
    database.execute(
        """
        insert into categorization_rules (
          id, pattern, match_type, category_id, transaction_class, priority, requires_review, active, notes, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, 1, ?, current_timestamp)
        on conflict(id) do update set
          pattern = excluded.pattern,
          match_type = excluded.match_type,
          category_id = excluded.category_id,
          transaction_class = excluded.transaction_class,
          priority = excluded.priority,
          requires_review = excluded.requires_review,
          active = excluded.active,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (rule_id, pattern, match_type, category_id, transaction_class, priority, int(requires_review), notes),
    )