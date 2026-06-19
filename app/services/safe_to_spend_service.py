from decimal import Decimal


def calculate_safe_to_spend(checking_balance: Decimal, bills_due_before_next_paycheck: Decimal, checking_floor: Decimal) -> Decimal:
    return checking_balance - bills_due_before_next_paycheck - checking_floor