from io import BytesIO


def seed_import(database, import_id: str = "import-routes"):
    database.execute(
        """
        insert into imports (id, account_id, import_profile_id, source_file_name, rows_read, new_transactions)
        values (?, 'acct-becu-checking', 'profile-becu-checking', 'routes.csv', 1, 1)
        """,
        (import_id,),
    )
    database.commit()


def seed_transaction(
    database,
    transaction_id: str,
    description: str,
    *,
    source_import_id: str = "import-routes",
    amount: float = -10.0,
    transaction_class: str = "needs_review",
    needs_review: int = 1,
    category_id=None,
):
    database.execute(
        """
        insert into transactions (
          id, transaction_date, posted_date, account_id, description, raw_description, merchant, amount, direction,
          transaction_class, category_id, needs_review, review_note, matched_rule_id, matched_rule_pattern, transaction_hash,
          raw_csv_row_json, source_import_id
        ) values (?, '2026-06-20', null, 'acct-becu-checking', ?, ?, ?, ?, 'outflow', ?, ?, ?, null, null, null, ?, '{}', ?)
        """,
        (
            transaction_id,
            description,
            description,
            description.title(),
            amount,
            transaction_class,
            category_id,
            needs_review,
            f"hash-{transaction_id}",
            source_import_id,
        ),
    )
    database.commit()


def test_dashboard_route_renders(client):
    response = client.get("/?window=current_month")

    assert response.status_code == 200
    assert "View Window" in response.get_data(as_text=True)


def test_save_balance_persists_row(client, database):
    response = client.post(
        "/balances",
        data={
            "account_id": "acct-becu-checking",
            "snapshot_date": "2026-06-20",
            "balance": "1234.56",
            "notes": "test snapshot",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    saved = database.execute(
        "select balance, notes from balance_snapshots where account_id = 'acct-becu-checking' order by created_at desc limit 1"
    ).fetchone()
    assert float(saved["balance"]) == 1234.56
    assert saved["notes"] == "test snapshot"


def test_save_settings_upserts_values(client, database):
    response = client.post(
        "/settings",
        data={
            "pay_frequency": "biweekly",
            "normal_paycheck_amount": "2200.00",
            "payday_anchor": "2026-06-20",
            "checking_floor": "600",
            "manual_bills_due_before_next_paycheck": "150",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    settings = database.execute("select setting_key, setting_value from user_settings").fetchall()
    settings_map = {row["setting_key"]: row["setting_value"] for row in settings}
    assert settings_map["normal_paycheck_amount"] == "2200.00"
    assert settings_map["checking_floor"] == "600"


def test_create_bill_and_contact_routes(client, database):
    bill_response = client.post(
        "/bills",
        data={
            "name": "Power Bill",
            "expected_amount": "90.00",
            "due_day": "15",
            "frequency": "monthly",
            "category_id": "category-utilities",
            "account_id": "acct-becu-checking",
            "notes": "monthly",
        },
        follow_redirects=False,
    )
    contact_response = client.post(
        "/contacts",
        data={
            "name": "Jamie",
            "relationship_type": "friend",
            "default_category_id": "category-household-reimbursement",
            "auto_apply": "on",
            "notes": "test contact",
        },
        follow_redirects=False,
    )

    assert bill_response.status_code == 302
    assert contact_response.status_code == 302
    bill = database.execute("select name from recurring_bills where name = 'Power Bill'").fetchone()
    contact = database.execute("select name from contacts where name = 'Jamie'").fetchone()
    assert bill is not None
    assert contact is not None


def test_import_get_renders_form(client):
    response = client.get("/import")

    assert response.status_code == 200
    assert "Import CSV" in response.get_data(as_text=True)


def test_import_preview_shows_form_error_on_value_error(client, monkeypatch):
    def fake_preview_import(*_args, **_kwargs):
        raise ValueError("Bad CSV format")

    monkeypatch.setattr("app.views.preview_import", fake_preview_import)

    response = client.post(
        "/import",
        data={
            "action": "preview",
            "account_id": "acct-becu-checking",
            "profile_id": "profile-becu-checking",
            "csv_file": (BytesIO(b"Date,Description,Amount\n"), "bad.csv"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "Bad CSV format" in response.get_data(as_text=True)


def test_import_action_renders_report(client, monkeypatch):
    monkeypatch.setattr("app.views.decode_upload", lambda _payload: b"csv")
    monkeypatch.setattr("app.views.preview_import", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "app.views.import_csv",
        lambda *_args, **_kwargs: {
            "rows_read": 2,
            "new_transactions": 1,
            "duplicates_skipped": 1,
            "errors": [],
            "needs_review_count": 0,
            "debug_report": None,
        },
    )

    response = client.post(
        "/import",
        data={
            "action": "import",
            "account_id": "acct-becu-checking",
            "profile_id": "profile-becu-checking",
            "source_file_name": "x.csv",
            "file_payload": "ignored",
        },
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Import Report" in page
    assert "Rows read" in page


def test_review_only_zelle_filter(client, database):
    seed_import(database)
    seed_transaction(database, "txn-zelle", "ZELLE TO ALEX")
    seed_transaction(database, "txn-other", "AMAZON MARKETPLACE")

    response = client.get("/review?only_zelle=1&limit=25&page=1")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ZELLE TO ALEX" in page
    assert "AMAZON MARKETPLACE" not in page


def test_review_save_transfer_without_category_defaults_to_ignore_bucket(client, database):
    seed_import(database)
    seed_transaction(database, "txn-transfer", "Transfer test")

    response = client.post(
        "/review/txn-transfer",
        data={
            "category_id": "",
            "new_category_name": "",
            "transaction_class": "transfer",
            "review_note": "transfer",
            "rule_source_description": "Transfer test",
            "next_account_id": "",
            "next_transaction_class": "",
            "next_search": "",
            "next_limit": "25",
            "next_page": "1",
            "next_only_zelle": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    saved = database.execute("select category_id from transactions where id = 'txn-transfer'").fetchone()
    assert saved["category_id"] == "category-transfers-ignore"


def test_review_save_can_create_rule(client, database, monkeypatch):
    seed_import(database)
    seed_transaction(database, "txn-rule", "Rule target")

    captured = {}

    def fake_create_rule_from_review(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.views.create_rule_from_review", fake_create_rule_from_review)

    response = client.post(
        "/review/txn-rule",
        data={
            "category_id": "category-groceries",
            "new_category_name": "",
            "transaction_class": "expense",
            "review_note": "create rule",
            "create_rule": "on",
            "rule_pattern_mode": "exact_description",
            "rule_source_description": "Rule target",
            "rule_pattern": "Rule target",
            "rule_match_type": "exact",
            "rule_priority": "777",
            "next_account_id": "",
            "next_transaction_class": "",
            "next_search": "",
            "next_limit": "25",
            "next_page": "1",
            "next_only_zelle": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert captured["pattern"] == "Rule target"
    assert captured["match_type"] == "exact"
    assert captured["priority"] == 777
    assert captured["category_id"] == "category-groceries"


def test_review_save_redirect_includes_scroll_position(client, database):
    seed_import(database)
    seed_transaction(database, "txn-scroll", "Scroll target")

    response = client.post(
        "/review/txn-scroll",
        data={
            "category_id": "category-groceries",
            "new_category_name": "",
            "transaction_class": "expense",
            "review_note": "keep scroll",
            "rule_source_description": "Scroll target",
            "next_account_id": "",
            "next_transaction_class": "",
            "next_search": "",
            "next_limit": "25",
            "next_page": "1",
            "next_only_zelle": "0",
            "next_scroll_y": "640",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "scroll_y=640" in response.headers["Location"]
