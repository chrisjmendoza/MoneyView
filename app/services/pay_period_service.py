from datetime import date, timedelta


def calculate_pay_period(anchor_date: date, reference_date: date, pay_frequency: str) -> dict:
    if pay_frequency != "biweekly":
        raise ValueError(f"Unsupported pay frequency: {pay_frequency}")

    cycle_days = 14
    delta_days = (reference_date - anchor_date).days
    completed_cycles = delta_days // cycle_days
    current_payday = anchor_date + timedelta(days=completed_cycles * cycle_days)

    if current_payday > reference_date:
        current_payday -= timedelta(days=cycle_days)

    next_payday = current_payday + timedelta(days=cycle_days)
    pay_period_end = next_payday - timedelta(days=1)

    return {
        "current_payday": current_payday,
        "next_payday": next_payday,
        "pay_period_start": current_payday,
        "pay_period_end": pay_period_end,
    }