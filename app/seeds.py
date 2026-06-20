import sqlite3


DEFAULT_ACCOUNTS = [
    ("acct-becu-checking", "BECU Checking", "BECU", "checking", "5651 * Primary Checking"),
    ("acct-becu-savings", "BECU Savings", "BECU", "savings", "5643 * Savings Account"),
    ("acct-chase-credit-card", "Chase Credit Card", "Chase", "credit_card", None),
    ("acct-becu-credit-card", "BECU Credit Card", "BECU", "credit_card", "5515 * Visa Credit Card"),
    ("acct-becu-loc", "BECU Line of Credit", "BECU", "line_of_credit", "2672 * Line of Credit"),
    ("acct-cash-wallet", "Cash Wallet", "Manual", "cash", None),
    ("acct-manual-other", "Manual Other", "Manual", "other", None),
]

DEFAULT_PROFILES = [
    {
        "id": "profile-becu-checking",
        "name": "BECU Checking CSV",
        "institution": "BECU",
        "account_type": "checking",
        "date_column": "Date",
        "posted_date_column": None,
        "account_column": "Account",
        "description_column": "Original Description|Description|Memo",
        "amount_column": "Amount",
        "type_column": "Type",
        "debit_column": None,
        "credit_column": None,
        "balance_column": "Balance",
        "date_format": "%m/%d/%Y|%m/%d/%y",
        "amount_sign_rule": "signed_amount_or_type_column",
        "has_header": 1,
        "active": 1,
        "notes": "Supports both signed-amount fixtures and real BECU exports that use Debit/Credit type plus 2-digit years.",
    },
    {
        "id": "profile-becu-savings",
        "name": "BECU Savings CSV",
        "institution": "BECU",
        "account_type": "savings",
        "date_column": "Date",
        "posted_date_column": None,
        "account_column": "Account",
        "description_column": "Original Description|Description|Memo",
        "amount_column": "Amount",
        "type_column": "Type",
        "debit_column": None,
        "credit_column": None,
        "balance_column": "Balance",
        "date_format": "%m/%d/%Y|%m/%d/%y",
        "amount_sign_rule": "signed_amount_or_type_column",
        "has_header": 1,
        "active": 1,
        "notes": "Supports both signed-amount fixtures and real BECU exports that use Debit/Credit type plus 2-digit years.",
    },
    {
        "id": "profile-generic-signed",
        "name": "Generic Signed Amount CSV",
        "institution": "Generic",
        "account_type": "checking",
        "date_column": "Date",
        "posted_date_column": None,
        "account_column": None,
        "description_column": "Description",
        "amount_column": "Amount",
        "debit_column": None,
        "credit_column": None,
        "balance_column": None,
        "date_format": "%Y-%m-%d",
        "amount_sign_rule": "signed_amount",
        "has_header": 1,
        "active": 1,
        "notes": "Generic signed amount CSV profile.",
    },
    {
        "id": "profile-generic-debit-credit",
        "name": "Generic Debit/Credit CSV",
        "institution": "Generic",
        "account_type": "checking",
        "date_column": "Date",
        "posted_date_column": None,
        "account_column": None,
        "description_column": "Description",
        "amount_column": None,
        "debit_column": "Debit",
        "credit_column": "Credit",
        "balance_column": None,
        "date_format": "%Y-%m-%d",
        "amount_sign_rule": "debit_credit_columns",
        "has_header": 1,
        "active": 1,
        "notes": "Generic separate debit and credit column profile.",
    },
    {
        "id": "profile-credit-card-positive-purchases",
        "name": "Credit Card Positive Purchases",
        "institution": "Generic",
        "account_type": "credit_card",
        "date_column": "Date",
        "posted_date_column": None,
        "account_column": None,
        "description_column": "Description",
        "amount_column": "Amount",
        "debit_column": None,
        "credit_column": None,
        "balance_column": None,
        "date_format": "%Y-%m-%d",
        "amount_sign_rule": "credit_card_positive_purchases",
        "has_header": 1,
        "active": 1,
        "notes": "Maps positive purchase amounts to internal outflow sign.",
    },
]

DEFAULT_CATEGORIES = [
    "Paycheck",
    "Rent",
    "Utilities",
    "Internet",
    "Insurance",
    "Car Payment",
    "Credit Card Payment",
    "LOC Draw",
    "Household Reimbursement",
    "Coffee Shops",
    "Groceries",
    "Fast Food",
    "Restaurants",
    "Fuel",
    "Therapy",
    "Gym",
    "AI Tools",
    "Subscriptions",
    "Auto / Car Projects",
    "Cycling",
    "RidePrint",
    "S2000",
    "Amazon / Shopping",
    "PayPal / Unknown",
    "Transfers / Ignore",
    "Needs Review",
]

DEFAULT_RULES = [
    ("rule-safeway-fuel", "SAFEWAY FUEL", "contains", "Fuel", "expense", 950, 0, "Fuel purchases before general Safeway grocery rule."),
    ("rule-urban-city-coffee", "URBAN CITY COFFEE", "contains", "Coffee Shops", "expense", 900, 0, "Starter Chris rule."),
    ("rule-gourmet-latte", "GOURMET LATTE", "contains", "Coffee Shops", "expense", 900, 0, "Starter Chris rule."),
    ("rule-qfc", "QFC", "contains", "Groceries", "expense", 900, 0, "Starter Chris rule."),
    ("rule-winco", "WINCO", "contains", "Groceries", "expense", 900, 0, "Starter Chris rule."),
    ("rule-safeway", "SAFEWAY", "contains", "Groceries", "expense", 850, 0, "Starter Chris rule."),
    ("rule-sound-prop", "SOUND PROP", "contains", "Paycheck", "income", 900, 0, "Starter Chris rule."),
    ("rule-ziply", "ZIPLY", "contains", "Internet", "expense", 900, 0, "Starter Chris rule."),
    ("rule-snohomish-pud", "SNOHOMISH COUNTY PUD", "contains", "Utilities", "expense", 900, 0, "Starter Chris rule."),
    ("rule-alderwood-water", "ALDERWOOD WATER", "contains", "Utilities", "expense", 900, 0, "Starter Chris rule."),
    ("rule-waste-management", "WASTE MANAGEMENT", "contains", "Utilities", "expense", 900, 0, "Starter Chris rule."),
    ("rule-usaa", "USAA", "contains", "Insurance", "expense", 900, 0, "Starter Chris rule."),
    ("rule-ivy", "IVY", "contains", "Therapy", "expense", 900, 0, "Starter Chris rule."),
    ("rule-planet-fitness", "PLANET FITNESS", "contains", "Gym", "expense", 900, 0, "Starter Chris rule."),
    ("rule-kitsap", "KITSAP", "contains", "Car Payment", "expense", 900, 0, "Starter Chris rule."),
    ("rule-openai", "OPENAI", "contains", "AI Tools", "expense", 900, 0, "Starter Chris rule."),
    ("rule-anthropic", "ANTHROPIC", "contains", "AI Tools", "expense", 900, 0, "Starter Chris rule."),
    ("rule-claude", "CLAUDE", "contains", "AI Tools", "expense", 900, 0, "Starter Chris rule."),
    ("rule-science-of-speed", "SCIENCE OF SPEED", "contains", "S2000", "expense", 900, 0, "Starter Chris rule."),
    ("rule-bicycle-centres", "BICYCLE CENTRES", "contains", "Needs Review", "expense", 900, 1, "Ambiguous merchant; ask every time."),
    ("rule-amazon", "AMAZON", "contains", "Needs Review", "expense", 900, 1, "Ambiguous merchant; ask every time."),
    ("rule-paypal", "PAYPAL", "contains", "Needs Review", "expense", 900, 1, "Ambiguous merchant; ask every time."),
    ("rule-cash-app", "CASH APP", "contains", "Needs Review", "expense", 900, 1, "Ambiguous merchant; ask every time."),
    ("rule-venmo", "VENMO", "contains", "Needs Review", "expense", 900, 1, "Ambiguous merchant; ask every time."),
]

DEFAULT_SETTINGS = [
    ("pay_frequency", "biweekly", "Current supported pay cadence."),
    ("normal_paycheck_amount", "2034.70", "Used for pay period context and later forecasting."),
    ("payday_anchor", "2026-06-19", "Anchor payday for biweekly cadence."),
    ("checking_floor", "500", "Minimum cash buffer to retain in checking."),
    ("manual_bills_due_before_next_paycheck", "0", "Optional manual override for bills due before next payday."),
]


def category_id(name: str) -> str:
    return f"category-{name.lower().replace(' / ', '-').replace(' ', '-')}"


def seed_defaults(database: sqlite3.Connection) -> None:
    for account_id, name, institution, account_type, external_account_ref in DEFAULT_ACCOUNTS:
        database.execute(
            """
            insert or ignore into accounts (id, name, institution, account_type, external_account_ref)
            values (?, ?, ?, ?, ?)
            """,
            (account_id, name, institution, account_type, external_account_ref),
        )
        database.execute(
            """
            update accounts
            set external_account_ref = coalesce(?, external_account_ref),
                updated_at = current_timestamp
            where id = ?
            """,
            (external_account_ref, account_id),
        )

    # Keep existing databases aligned with clearer account naming.
    database.execute(
        """
        update accounts
        set name = 'BECU Line of Credit',
            updated_at = current_timestamp
        where id = 'acct-becu-loc' and name = 'BECU LOC'
        """
    )

    for profile in DEFAULT_PROFILES:
        database.execute(
            """
            insert or ignore into import_profiles (
              id, name, institution, account_type, date_column, posted_date_column,
                            account_column, description_column, amount_column, type_column, debit_column, credit_column,
              balance_column, date_format, amount_sign_rule, has_header, active, notes
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile["id"],
                profile["name"],
                profile["institution"],
                profile["account_type"],
                profile["date_column"],
                profile["posted_date_column"],
                                profile.get("account_column"),
                profile["description_column"],
                profile["amount_column"],
                profile.get("type_column"),
                profile["debit_column"],
                profile["credit_column"],
                profile["balance_column"],
                profile["date_format"],
                profile["amount_sign_rule"],
                profile["has_header"],
                profile["active"],
                profile["notes"],
            ),
        )

        database.execute(
            """
            update import_profiles
            set date_column = ?,
                posted_date_column = ?,
                account_column = ?,
                description_column = ?,
                amount_column = ?,
                type_column = ?,
                debit_column = ?,
                credit_column = ?,
                balance_column = ?,
                date_format = ?,
                amount_sign_rule = ?,
                notes = ?,
                updated_at = current_timestamp
            where id = ?
            """,
            (
                profile["date_column"],
                profile["posted_date_column"],
                profile.get("account_column"),
                profile["description_column"],
                profile["amount_column"],
                profile.get("type_column"),
                profile["debit_column"],
                profile["credit_column"],
                profile["balance_column"],
                profile["date_format"],
                profile["amount_sign_rule"],
                profile["notes"],
                profile["id"],
            ),
        )

    for name in DEFAULT_CATEGORIES:
        database.execute(
            "insert or ignore into categories (id, name, notes) values (?, ?, ?)",
            (category_id(name), name, "Seeded default category."),
        )

    for rule_id, pattern, match_type, category_name, transaction_class, priority, requires_review, notes in DEFAULT_RULES:
        database.execute(
            """
            insert or ignore into categorization_rules (
              id, pattern, match_type, category_id, transaction_class, priority, requires_review, active, notes
            ) values (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                rule_id,
                pattern,
                match_type,
                category_id(category_name),
                transaction_class,
                priority,
                requires_review,
                notes,
            ),
        )

    database.execute(
        """
        update categorization_rules
        set active = 0,
            notes = 'Legacy blanket Zelle rule disabled in favor of contact-based review handling.',
            updated_at = current_timestamp
        where id = 'rule-zelle-from'
        """
    )

    for setting_key, setting_value, notes in DEFAULT_SETTINGS:
        database.execute(
            "insert or ignore into user_settings (id, setting_key, setting_value, notes) values (?, ?, ?, ?)",
            (f"setting-{setting_key}", setting_key, setting_value, notes),
        )