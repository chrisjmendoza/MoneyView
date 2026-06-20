# MoneyView — Improvement Backlog

Generated from multi-perspective analysis (user / developer / engineer / financial expert).

---

## Tier 1 — Safety & Correctness Fixes

- [x] SQLite `PRAGMA foreign_keys = ON` — already present in db.py
- [x] Add WAL mode (`PRAGMA journal_mode = WAL`) to db.py
- [x] Replace `abs(hash(...))` IDs with `uuid4()` in views.py (bills, contacts, balance snapshots)
- [x] Move `SECRET_KEY` out of source — read from `SECRET_KEY` env var with fallback warning
- [x] Fix `insert or replace` on rules → `ON CONFLICT DO UPDATE` to preserve `created_at`
- [x] Flash messages on all form POSTs (save_settings, create_bill, create_contact, save_balance, update_review)

## Tier 2 — High-Value Missing Features

- [x] Rules management page `/rules` — list, toggle active, edit pattern/category, delete
- [x] Transaction browser `/transactions` — all transactions, filterable, paginated (not just review queue)
- [x] Edit any transaction from the browser (re-open review for already-reviewed transactions)
- [x] Recurring bills management `/bills` — dedicated page, edit and delete existing bills
- [ ] Import history + rollback — list past imports, delete an import and its transactions

## Tier 3 — Financial Correctness Gaps

- [ ] Net refunds against category totals in top-categories query (currently excludes positive-amount expense-class rows)
- [ ] Weekly / annual bill frequency support in `compute_bills_due_before_next_paycheck`
- [ ] Remove hardcoded `SOUND PROP` employer name from sanity warnings → make it a `payroll_description_hint` user setting
- [ ] Remove hardcoded `FOOD_CATEGORIES` category name strings in dashboard_service → reference by ID
- [ ] Multi-period trend view (3-month rolling category averages)

## Tier 4 — Security

- [ ] CSRF token on all POST forms (Flask session-based token, no external dep required)
- [ ] Input validation on `/settings` POST — validate date format, decimal fields before DB write
- [ ] Rate-limit or size-cap on `/import` CSV upload payload

## Tier 5 — Growth Features (Post-MVP)

- [ ] Budget vs. actual per category (set monthly target, track vs. real spend)
- [ ] Net worth snapshot view (assets − liabilities across all accounts)
- [ ] Annual projections from current pay-period rate
- [ ] Spending trend sparklines per category
- [ ] Export filtered transactions to CSV
