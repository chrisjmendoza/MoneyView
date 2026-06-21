import sqlite3
from datetime import date
from decimal import Decimal

from .pay_period_service import calculate_pay_period
from .safe_to_spend_service import calculate_safe_to_spend


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


def _next_monthly_due(today: date, due_day: int) -> date:
    clamped = min(due_day, 28)
    candidate = date(today.year, today.month, clamped)
    if candidate < today:
        if today.month == 12:
            candidate = date(today.year + 1, 1, clamped)
        else:
            candidate = date(today.year, today.month + 1, clamped)
    return candidate


def compute_bills_due_before_next_paycheck(database: sqlite3.Connection, today: date, next_payday: date, manual_override: Decimal) -> Decimal:
    if manual_override > Decimal("0"):
        return manual_override

    total = Decimal("0")
    rows = database.execute(
        """
        select expected_amount, due_day, due_month, frequency, is_shared, split_count
        from recurring_bills
        where active = 1
        """
    ).fetchall()

    days_until_payday = (next_payday - today).days

    for row in rows:
        due_amount = Decimal(str(row["expected_amount"]))
        if row["is_shared"] and row["split_count"]:
            due_amount = due_amount / Decimal(str(row["split_count"]))

        frequency = row["frequency"]

        if frequency == "monthly":
            due_date = _next_monthly_due(today, int(row["due_day"]))
            if today <= due_date < next_payday:
                total += due_amount

        elif frequency == "weekly":
            # Count how many weekly occurrences fall before the next paycheck.
            occurrences = max(days_until_payday // 7, 0)
            total += due_amount * occurrences

        elif frequency == "annual":
            due_month = row["due_month"]
            if not due_month:
                continue
            try:
                due_date = date(today.year, int(due_month), min(int(row["due_day"]), 28))
            except ValueError:
                continue
            if due_date < today:
                due_date = date(today.year + 1, int(due_month), min(int(row["due_day"]), 28))
            if today <= due_date < next_payday:
                total += due_amount

    return total


def summarize_data_confidence(row: dict) -> dict:
    total_transactions = int(row["total_transactions"] or 0)
    categorized_transactions = int(row["categorized_transactions"] or 0)
    percent_categorized = (categorized_transactions / total_transactions * 100) if total_transactions else 100.0
    return {
        "total_transactions": total_transactions,
        "categorized_transactions": categorized_transactions,
        "needs_review_count": int(row["needs_review_count"] or 0),
        "needs_review_total": row["needs_review_total"],
        "percent_categorized": percent_categorized,
    }


def compute_net_worth(balances: list) -> Decimal:
    asset_types = {"checking", "savings", "cash"}
    liability_types = {"credit_card", "line_of_credit", "loan"}
    total = Decimal("0")
    for balance in balances:
        if balance["balance"] is None:
            continue
        amt = Decimal(str(balance["balance"]))
        if balance["account_type"] in asset_types:
            total += amt
        elif balance["account_type"] in liability_types:
            total -= amt
    return total


def latest_import_status(database: sqlite3.Connection) -> dict | None:
    return database.execute(
        """
        select
          imports.imported_at,
          imports.source_file_name,
          imports.rows_read,
          imports.new_transactions,
          imports.duplicates_skipped,
          imports.errors_count,
          imports.needs_review_count,
          accounts.name as account_name,
          import_profiles.name as profile_name
        from imports
        join accounts on accounts.id = imports.account_id
        join import_profiles on import_profiles.id = imports.import_profile_id
        order by imports.imported_at desc, imports.id desc
        limit 1
        """
    ).fetchone()


def spending_trend_by_category_month(database: sqlite3.Connection, num_months: int = 3) -> dict:
    rows = database.execute(
        """
        select
          strftime('%Y-%m', transaction_date) as month,
          coalesce(categories.name, 'Uncategorized') as category_name,
          round(sum(
            case when amount < 0 then abs(amount) else -amount end
          ), 2) as net_spend
        from transactions
        left join categories on categories.id = transactions.category_id
        where transaction_class in ('expense', 'refund')
          and transaction_date >= date('now', ? || ' months')
        group by month, category_name
        having net_spend > 0
        order by category_name asc, month asc
        """,
        (f"-{num_months}",),
    ).fetchall()

    all_months = sorted({r["month"] for r in rows})
    cat_data: dict[str, dict[str, float]] = {}
    for r in rows:
        cat_data.setdefault(r["category_name"], {})[r["month"]] = float(r["net_spend"])

    return {cat: [month_data.get(m, 0.0) for m in all_months] for cat, month_data in cat_data.items()}


_PAY_PERIODS_PER_YEAR: dict[str, int] = {
    "biweekly": 26,
    "weekly": 52,
    "semimonthly": 24,
    "monthly": 12,
}


def compute_annual_projection(spending_trend: list[dict], settings: dict) -> dict:
    paycheck = Decimal(str(settings.get("normal_paycheck_amount", "0") or "0"))
    periods = _PAY_PERIODS_PER_YEAR.get(settings.get("pay_frequency", "biweekly"), 26)
    annual_income = paycheck * periods

    if spending_trend:
        total_expense = sum(Decimal(str(r["net_spend"] or 0)) for r in spending_trend)
        annual_expense = (total_expense / len(spending_trend)) * 12
        based_on_months = len(spending_trend)
    else:
        annual_expense = Decimal("0")
        based_on_months = 0

    return {
        "income": annual_income,
        "expense": annual_expense,
        "net": annual_income - annual_expense,
        "pay_periods": periods,
        "based_on_months": based_on_months,
    }


def budget_vs_actual(database: sqlite3.Connection, year: int, month: int) -> list[dict]:
    month_str = f"{year:04d}-{month:02d}"
    rows = database.execute(
        """
        select
          c.id as category_id,
          c.name as category_name,
          coalesce(cb.monthly_limit, 0) as monthly_limit,
          coalesce(spend.total_spend, 0) as actual_spend
        from categories c
        left join category_budgets cb on cb.category_id = c.id
        left join (
          select category_id,
                 round(sum(case when amount < 0 then abs(amount) else -amount end), 2) as total_spend
          from transactions
          where transaction_class in ('expense', 'refund')
            and strftime('%Y-%m', transaction_date) = ?
          group by category_id
        ) spend on spend.category_id = c.id
        where c.active = 1
          and (cb.category_id is not null or spend.category_id is not null)
        order by coalesce(spend.total_spend, 0) desc, c.name asc
        """,
        (month_str,),
    ).fetchall()
    result = []
    for r in rows:
        budget = Decimal(str(r["monthly_limit"]))
        actual = Decimal(str(r["actual_spend"]))
        result.append({
            "category_id": r["category_id"],
            "category_name": r["category_name"],
            "budget": float(budget),
            "actual": float(actual),
            "pct": float(actual / budget * 100) if budget > 0 else None,
        })
    return result


def spending_trend_by_month(database: sqlite3.Connection, num_months: int = 3) -> list[dict]:
    rows = database.execute(
        """
        select
          strftime('%Y-%m', transaction_date) as month,
          round(sum(
            case when amount < 0 then abs(amount) else -amount end
          ), 2) as net_spend,
          round(sum(case when amount < 0 then abs(amount) else 0 end), 2) as gross_expense,
          round(sum(case when amount > 0 and transaction_class = 'refund' then amount else 0 end), 2) as refunds
        from transactions
        where transaction_class in ('expense', 'refund')
          and transaction_date >= date('now', ? || ' months')
        group by month
        order by month asc
        """,
        (f"-{num_months}",),
    ).fetchall()
    return [dict(r) for r in rows]


def build_sanity_warnings(
    database: sqlite3.Connection,
    range_start_iso: str,
    range_end_iso: str,
    pay_period: dict,
    normal_paycheck_amount: Decimal,
    checking_balance_found: bool,
    bills_due_auto: Decimal,
    manual_bills_override: Decimal,
    data_confidence: dict,
    payroll_description_hint: str = "",
) -> list[dict]:
    warnings: list[dict] = []

    mismatch = database.execute(
        """
        select
          sum(case when categories.name = 'Household Reimbursement' and transactions.transaction_class = 'income' then 1 else 0 end) as reimbursements_as_income_count,
          coalesce(sum(case when categories.name = 'Household Reimbursement' and transactions.transaction_class = 'income' then abs(transactions.amount) else 0 end), 0) as reimbursements_as_income_total,
          sum(case when categories.name = 'LOC Draw' and transactions.transaction_class = 'income' then 1 else 0 end) as loc_as_income_count,
          coalesce(sum(case when categories.name = 'LOC Draw' and transactions.transaction_class = 'income' then abs(transactions.amount) else 0 end), 0) as loc_as_income_total,
          sum(case when categories.name = 'Credit Card Payment' and transactions.transaction_class = 'expense' then 1 else 0 end) as cc_as_expense_count,
          coalesce(sum(case when categories.name = 'Credit Card Payment' and transactions.transaction_class = 'expense' then abs(transactions.amount) else 0 end), 0) as cc_as_expense_total,
          sum(case when transactions.transaction_class = 'expense' and (categories.name = 'Transfers / Ignore' or upper(transactions.description) like '%TRANSFER%' or upper(transactions.description) like '%XFER%' or upper(transactions.description) like '%TRNSFR%') then 1 else 0 end) as transfer_as_expense_count,
          coalesce(sum(case when transactions.transaction_class = 'expense' and (categories.name = 'Transfers / Ignore' or upper(transactions.description) like '%TRANSFER%' or upper(transactions.description) like '%XFER%' or upper(transactions.description) like '%TRNSFR%') then abs(transactions.amount) else 0 end), 0) as transfer_as_expense_total
        from transactions
        left join categories on categories.id = transactions.category_id
        where transactions.transaction_date between ? and ?
        """,
        (range_start_iso, range_end_iso),
    ).fetchone()

    if int(mismatch["reimbursements_as_income_count"] or 0) > 0:
        warnings.append(
            {
                "code": "reimbursements_counted_as_income",
                "message": f"{int(mismatch['reimbursements_as_income_count'])} reimbursement transaction(s) totaling ${float(mismatch['reimbursements_as_income_total'] or 0):.2f} are marked as income.",
            }
        )

    if int(mismatch["loc_as_income_count"] or 0) > 0:
        warnings.append(
            {
                "code": "loc_draws_counted_as_income",
                "message": f"{int(mismatch['loc_as_income_count'])} line of credit draw transaction(s) totaling ${float(mismatch['loc_as_income_total'] or 0):.2f} are marked as income.",
            }
        )

    if int(mismatch["cc_as_expense_count"] or 0) > 0:
        warnings.append(
            {
                "code": "credit_card_payments_as_expense",
                "message": f"{int(mismatch['cc_as_expense_count'])} credit card payment transaction(s) totaling ${float(mismatch['cc_as_expense_total'] or 0):.2f} are marked as ordinary expense.",
            }
        )

    if int(mismatch["transfer_as_expense_count"] or 0) > 0:
        warnings.append(
            {
                "code": "transfers_as_expense",
                "message": f"{int(mismatch['transfer_as_expense_count'])} transfer transaction(s) totaling ${float(mismatch['transfer_as_expense_total'] or 0):.2f} are marked as ordinary expense.",
            }
        )

    review_count = int(data_confidence["needs_review_count"] or 0)
    total_count = int(data_confidence["total_transactions"] or 0)
    review_total = Decimal(str(data_confidence["needs_review_total"] or 0))
    review_ratio = Decimal(str(review_count)) / Decimal(str(total_count)) if total_count else Decimal("0")

    if review_ratio > Decimal("0.20"):
        warnings.append(
            {
                "code": "review_ratio_high",
                "message": f"Unknown/review transactions are {review_ratio * 100:.1f}% of this window ({review_count} of {total_count}).",
            }
        )

    if review_total > Decimal("300"):
        warnings.append(
            {
                "code": "review_total_high",
                "message": f"Unknown/review total is ${float(review_total):.2f}, above the $300 safety threshold.",
            }
        )

    if normal_paycheck_amount > Decimal("0"):
        hint_clause = ""
        hint_params: list = []
        if payroll_description_hint.strip():
            hint_clause = "or upper(transactions.description) like ?"
            hint_params = [f"%{payroll_description_hint.strip().upper()}%"]
        paycheck_count = database.execute(
            f"""
            select count(*) as paycheck_count
            from transactions
            left join categories on categories.id = transactions.category_id
            where transactions.transaction_date between ? and ?
              and transactions.transaction_class = 'income'
              and (
                categories.name = 'Paycheck'
                or upper(transactions.description) like '%PAYROLL%'
                {hint_clause}
              )
            """,
            (pay_period["current_payday"].isoformat(), pay_period["pay_period_end"].isoformat(), *hint_params),
        ).fetchone()["paycheck_count"]
        if int(paycheck_count or 0) == 0:
            warnings.append(
                {
                    "code": "no_paycheck_detected",
                    "message": "No paycheck-like income was detected in the current pay period window.",
                }
            )

    if not checking_balance_found:
        warnings.append(
            {
                "code": "missing_checking_balance",
                "message": "Safe-to-spend cannot be calculated reliably because no checking balance snapshot was found.",
            }
        )

    if manual_bills_override > Decimal("0"):
        warnings.append(
            {
                "code": "manual_bills_override",
                "message": f"Bills due before next paycheck is manually overridden to ${float(manual_bills_override):.2f}.",
            }
        )
    elif bills_due_auto == Decimal("0"):
        warnings.append(
            {
                "code": "bills_due_missing",
                "message": "No bills due before next paycheck were detected; verify recurring bills and due days.",
            }
        )

    return warnings


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
    checking_balance_found = False

    for balance in balances:
        if balance["account_type"] == "checking" and balance["balance"] is not None:
            checking_balance = Decimal(str(balance["balance"]))
            checking_balance_found = True
            break

    manual_bills_override = Decimal(settings.get("manual_bills_due_before_next_paycheck", "0"))
    bills_due_auto = compute_bills_due_before_next_paycheck(
        database,
        today,
        pay_period["next_payday"],
        Decimal("0"),
    )
    bills_due = compute_bills_due_before_next_paycheck(
        database,
        today,
        pay_period["next_payday"],
        manual_bills_override,
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

    data_confidence_row = database.execute(
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

    all_data_confidence_row = database.execute(
        """
        select
          count(*) as total_transactions,
          sum(case when category_id is not null and transaction_class <> 'needs_review' and needs_review = 0 then 1 else 0 end) as categorized_transactions,
          sum(case when needs_review = 1 or category_id is null or transaction_class = 'needs_review' then 1 else 0 end) as needs_review_count,
          coalesce(sum(case when needs_review = 1 or category_id is null or transaction_class = 'needs_review' then abs(amount) else 0 end), 0) as needs_review_total
        from transactions
        """
    ).fetchone()

    data_confidence = summarize_data_confidence(data_confidence_row)
    all_data_confidence = summarize_data_confidence(all_data_confidence_row)

    sanity_warnings = build_sanity_warnings(
        database=database,
        range_start_iso=range_start_iso,
        range_end_iso=range_end_iso,
        pay_period=pay_period,
        normal_paycheck_amount=Decimal(settings.get("normal_paycheck_amount", "0")),
        checking_balance_found=checking_balance_found,
        bills_due_auto=bills_due_auto,
        manual_bills_override=manual_bills_override,
        data_confidence=data_confidence_row,
        payroll_description_hint=settings.get("payroll_description_hint", ""),
    )

    top_categories = database.execute(
        """
        select coalesce(categories.name, 'Uncategorized') as category_name,
               round(sum(
                 case when transactions.amount < 0 then abs(transactions.amount)
                      else -transactions.amount
                 end
               ), 2) as total_spend
        from transactions
        left join categories on categories.id = transactions.category_id
        where transactions.transaction_class in ('expense', 'refund')
          and transactions.transaction_date between ? and ?
        group by coalesce(categories.name, 'Uncategorized')
        having total_spend > 0
        order by total_spend desc
        limit 10
        """,
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

    spending_trend = spending_trend_by_month(database)
    return {
        "summary": summary,
        "data_confidence": data_confidence,
        "all_data_confidence": all_data_confidence,
        "net_worth": compute_net_worth(balances),
        "spending_trend": spending_trend,
        "annual_projection": compute_annual_projection(spending_trend, settings),
        "category_sparklines": spending_trend_by_category_month(database),
        "latest_import": latest_import_status(database),
        "top_categories": top_categories,
        "review_transactions": review_transactions,
        "balances": balances,
        "accounts": database.execute("select * from accounts where active = 1 order by name asc").fetchall(),
        "categories": database.execute("select * from categories where active = 1 order by name asc").fetchall(),
        "contacts": database.execute(
            """
            select contacts.*, categories.name as default_category_name
            from contacts
            left join categories on categories.id = contacts.default_category_id
            where contacts.active = 1
            order by contacts.name asc
            """
        ).fetchall(),
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
        "sanity_warnings": sanity_warnings,
        "sanity_warning_count": len(sanity_warnings),
    }