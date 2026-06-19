ACCOUNT_TYPES = {
    "checking",
    "savings",
    "credit_card",
    "line_of_credit",
    "loan",
    "cash",
    "other",
}

TRANSACTION_CLASSES = {
    "income",
    "expense",
    "debt_payment",
    "debt_draw",
    "transfer",
    "reimbursement",
    "refund",
    "fee_interest",
    "ignore",
    "needs_review",
}

SPENDING_CLASSES = {"expense"}
NON_SPENDING_CLASSES = {"debt_payment", "debt_draw", "transfer", "reimbursement", "ignore", "needs_review"}