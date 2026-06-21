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
- [x] Import history + rollback — `/imports` page lists all past imports; rollback deletes transactions and import record

## Tier 3 — Financial Correctness Gaps

- [x] Net refunds against category totals in top-categories query — expenses and refunds are now netted per category
- [x] Weekly / annual bill frequency support in `compute_bills_due_before_next_paycheck` — `due_month` column added for annual bills
- [x] Remove hardcoded `SOUND PROP` employer name from sanity warnings → `payroll_description_hint` user setting (configurable on dashboard)
- [x] Remove unused `FOOD_CATEGORIES` dead code from dashboard_service
- [x] 3-month spending trend — monthly gross/refund/net breakdown added to dashboard

## Tier 4 — Security

- [ ] CSRF token on all POST forms (Flask session-based token, no external dep required)
- [x] Input validation on `/settings` POST — date format and decimal fields validated before DB write
- [x] Size cap on `/import` CSV upload — `MAX_CONTENT_LENGTH = 10 MB` with flash error on 413

## Tier 5 — Growth Features (Post-MVP)

- [ ] Budget vs. actual per category (set monthly target, track vs. real spend)
- [x] Net worth snapshot on dashboard — assets minus liabilities from latest balance snapshots
- [ ] Annual projections from current pay-period rate
- [ ] Spending trend sparklines per category
- [x] Export filtered transactions to CSV — `/transactions/export` respects all active filters
