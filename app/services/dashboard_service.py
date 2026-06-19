import sqlite3
from datetime import date
from decimal import Decimal

from .pay_period_service import calculate_pay_period
from .safe_to_spend_service import calculate_safe_to_spend


FOOD_CATEGORIES = ("Groceries", "Fast Food", "Restaurants")


def resolve_window_range(window: str, today: date, pay_period: dict) -> tuple[date, date]:
    if window == "previous_pay_period":
        period_days = (pay_period["next_payday"] - pay_period["current_payday"]).days
        period_end = pay_period["current_payday"] - date.resolution
        period_start = period_end - (period_days - 1) * date.resolution
        return period_start, period_end

    if window == "current_month":
        return date(today.year, today.month, 1), today

    return pay_period["current_payday"], pay_period["pay_period_end"]


def load_settings(database: sqlite3.Connection) -> dict:
    rows = database.execute("select setting_key, setting_value from user_settings").fetchall()
    return {row["setting_key"]: row["setting_value"] for row in rows}


def latest_balances(database: sqlite3.Connection) -> list[dict]:
    return database.execute(
        """
        select a.id, a.name, a.institution, a.account_type, bs.balance, bs.snapshot_date
        from accounts a
        left join balance_snapshots bs on bs.id = (
          select inner_bs.id
          from balance_snapshots inner_bs
          where inner_bs.account_id = a.id
          order by inner_bs.snapshot_date desc, inner_bs.created_at desc
          limit 1
        )
        where a.active = 1
        order by a.name asc
        """
    ).fetchall()


def compute_bills_due_before_next_paycheck(database: sqlite3.Connection, today: date, next_payday: date, manual_override: Decimal) -> Decimal:
    if manual_override > Decimal("0"):
        return manual_override

    total = Decimal("0")
    rows = database.execute(
        """
        select expected_amount, due_day, is_shared, split_count
        from recurring_bills
        where active = 1 and frequency = 'monthly'
        """
    ).fetchall()

    for row in rows:
        due_amount = Decimal(str(row["expected_amount"]))
        if row["is_shared"] and row["split_count"]:
            due_amount = due_amount / Decimal(str(row["split_count"]))

        due_date = date(today.year, today.month, min(int(row["due_day"]), 28))
        if due_date < today:
            if today.month == 12:
                due_date = date(today.year + 1, 1, min(int(row["due_day"]), 28))
            else:
                due_date = date(today.year, today.month + 1, min(int(row["due_day"]), 28))

        if today <= due_date < next_payday:
            total += due_amount

    return total


def build_dashboard(database: sqlite3.Connection, today: date | None = None, window: str = "current_pay_period") -> dict:
    today = today or date.today()
    settings = load_settings(database)
    pay_period = calculate_pay_period(
        anchor_date=date.fromisoformat(settings["payday_anchor"]),
        reference_date=today,
        pay_frequency=settings["pay_frequency"],
    )
    range_start, range_end = resolve_window_range(window, today, pay_period)
    balances = latest_balances(database)
    checking_balance = Decimal("0")

    for balance in balances:
        if balance["account_type"] == "checking" and balance["balance"] is not None:
            checking_balance = Decimal(str(balance["balance"]))
            break

    bills_due = compute_bills_due_before_next_paycheck(
        database,
        today,
        pay_period["next_payday"],
        Decimal(settings.get("manual_bills_due_before_next_paycheck", "0")),
    )
    safe_to_spend = calculate_safe_to_spend(
        checking_balance,
        bills_due,
        Decimal(settings.get("checking_floor", "500")),
    )

    range_start_iso = range_start.isoformat()
    range_end_iso = range_end.isoformat()

    summary = database.execute(
        """
        select
          min(transaction_date) as start_date,
          max(transaction_date) as end_date,
          coalesce(sum(case when transaction_class = 'income' then amount else 0 end), 0) as normal_income_total,
          coalesce(sum(case when transaction_class = 'reimbursement' then amount else 0 end), 0) as reimbursement_total,
          coalesce(sum(case when transaction_class = 'debt_draw' then abs(amount) else 0 end), 0) as debt_draw_total,
          coalesce(sum(case when transaction_class = 'expense' and amount < 0 then abs(amount) else 0 end), 0) as normal_expense_total,
          coalesce(sum(case when transaction_class = 'debt_payment' then abs(amount) else 0 end), 0) as debt_payment_total,
          coalesce(sum(case when transaction_class in ('transfer', 'ignore') then abs(amount) else 0 end), 0) as transfer_ignore_total,
          coalesce(sum(case when categories.name = 'Coffee Shops' and transaction_class = 'expense' and amount < 0 then abs(amount) else 0 end), 0) as coffee_total,
          coalesce(sum(case when categories.name in ('Groceries', 'Fast Food', 'Restaurants') and transaction_class = 'expense' and amount < 0 then abs(amount) else 0 end), 0) as food_total,
          coalesce(sum(case when categories.name = 'LOC Draw' and transaction_class = 'debt_draw' then abs(amount) else 0 end), 0) as loc_draw_total,
          coalesce(sum(case when categories.name = 'Credit Card Payment' and transaction_class = 'debt_payment' then abs(amount) else 0 end), 0) as credit_card_payment_total,
          coalesce(sum(case when transactions.needs_review = 1 or transactions.category_id is null or transaction_class = 'needs_review' then abs(amount) else 0 end), 0) as unknown_review_total
        from transactions
        left join categories on categories.id = transactions.category_id
        where transactions.transaction_date between ? and ?
        """
    ,
        (range_start_iso, range_end_iso),
    ).fetchone()

    data_confidence = database.execute(
        """
        select
          count(*) as total_transactions,
          sum(case when category_id is not null and transaction_class <> 'needs_review' and needs_review = 0 then 1 else 0 end) as categorized_transactions,
          sum(case when needs_review = 1 or category_id is null or transaction_class = 'needs_review' then 1 else 0 end) as needs_review_count,
          coalesce(sum(case when needs_review = 1 or category_id is null or transaction_class = 'needs_review' then abs(amount) else 0 end), 0) as needs_review_total
        from transactions
        where transaction_date between ? and ?
        """,
        (range_start_iso, range_end_iso),
    ).fetchone()

    total_transactions = int(data_confidence["total_transactions"] or 0)
    categorized_transactions = int(data_confidence["categorized_transactions"] or 0)
    percent_categorized = (categorized_transactions / total_transactions * 100) if total_transactions else 100.0

    top_categories = database.execute(
        """
        select coalesce(categories.name, 'Uncategorized') as category_name,
               round(sum(abs(transactions.amount)), 2) as total_spend
        from transactions
        left join categories on categories.id = transactions.category_id
        where transactions.amount < 0
          and transactions.transaction_class = 'expense'
          and transactions.transaction_date between ? and ?
        group by coalesce(categories.name, 'Uncategorized')
        order by total_spend desc
        limit 10
        """
    ,
        (range_start_iso, range_end_iso),
    ).fetchall()

    review_transactions = database.execute(
        """
        select transactions.id, transactions.transaction_date, transactions.description, transactions.amount,
               transactions.transaction_class, categories.name as category_name
        from transactions
        left join categories on categories.id = transactions.category_id
        where (transactions.needs_review = 1 or transactions.category_id is null or transactions.transaction_class = 'needs_review')
          and transactions.transaction_date between ? and ?
        order by transactions.transaction_date desc, transactions.created_at desc
        limit 10
        """
    ,
        (range_start_iso, range_end_iso),
    ).fetchall()

    recurring_bills = database.execute(
        """
        select recurring_bills.*, categories.name as category_name, accounts.name as account_name
        from recurring_bills
        left join categories on categories.id = recurring_bills.category_id
        left join accounts on accounts.id = recurring_bills.account_id
        where recurring_bills.active = 1
        order by recurring_bills.due_day asc, recurring_bills.name asc
        """
    ).fetchall()

    return {
        "summary": summary,
        "data_confidence": {
            "total_transactions": total_transactions,
            "categorized_transactions": categorized_transactions,
            "needs_review_count": int(data_confidence["needs_review_count"] or 0),
            "needs_review_total": data_confidence["needs_review_total"],
            "percent_categorized": percent_categorized,
        },
        "top_categories": top_categories,
        "review_transactions": review_transactions,
        "balances": balances,
        "accounts": database.execute("select * from accounts where active = 1 order by name asc").fetchall(),
        "categories": database.execute("select * from categories where active = 1 order by name asc").fetchall(),
        "recurring_bills": recurring_bills,
        "settings": settings,
        "window": window,
        "range": {
            "start": range_start_iso,
            "end": range_end_iso,
        },
        "pay_period": pay_period,
        "bills_due_before_next_paycheck": bills_due,
        "safe_to_spend": safe_to_spend,
    }