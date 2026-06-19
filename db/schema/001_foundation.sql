-- MoneyView foundation schema (generic CSV import architecture)

pragma foreign_keys = on;

create table if not exists accounts (
  id text primary key,
  name text not null,
  institution text not null,
  account_type text not null,
  external_account_ref text,
  active integer not null default 1,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  check(account_type in ('checking', 'savings', 'credit_card', 'line_of_credit', 'loan', 'cash', 'other'))
);

create table if not exists import_profiles (
  id text primary key,
  name text not null,
  institution text not null,
  account_type text not null,
  date_column text not null,
  posted_date_column text,
  description_column text not null,
  amount_column text,
  debit_column text,
  credit_column text,
  balance_column text,
  date_format text not null,
  amount_sign_rule text not null,
  has_header integer not null default 1,
  active integer not null default 1,
  notes text,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(name, institution, account_type)
);

create table if not exists imports (
  id text primary key,
  account_id text not null references accounts(id),
  import_profile_id text not null references import_profiles(id),
  source_file_name text not null,
  imported_at text not null default current_timestamp,
  rows_read integer not null default 0,
  new_transactions integer not null default 0,
  duplicates_skipped integer not null default 0,
  errors_count integer not null default 0,
  needs_review_count integer not null default 0,
  error_summary text
);

create table if not exists categories (
  id text primary key,
  name text not null unique,
  active integer not null default 1,
  notes text,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp
);

create table if not exists transactions (
  id text primary key,
  transaction_date text not null,
  posted_date text,
  account_id text not null references accounts(id),
  description text not null,
  raw_description text not null,
  merchant text,
  amount numeric not null,
  direction text not null,
  transaction_class text not null,
  category_id text references categories(id),
  needs_review integer not null default 0,
  review_note text,
  matched_rule_id text references categorization_rules(id),
  matched_rule_pattern text,
  transaction_hash text not null,
  raw_csv_row_json text not null,
  source_import_id text not null references imports(id),
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  unique(account_id, transaction_hash),
  check(direction in ('inflow', 'outflow')),
  check(transaction_class in (
    'income',
    'expense',
    'debt_payment',
    'debt_draw',
    'transfer',
    'reimbursement',
    'refund',
    'fee_interest',
    'ignore',
    'needs_review'
  ))
);

create table if not exists categorization_rules (
  id text primary key,
  pattern text not null,
  match_type text not null,
  category_id text references categories(id),
  transaction_class text,
  priority integer not null default 100,
  requires_review integer not null default 0,
  active integer not null default 1,
  notes text,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  check(match_type in ('contains', 'exact', 'regex'))
);

create table if not exists balance_snapshots (
  id text primary key,
  account_id text not null references accounts(id),
  snapshot_date text not null,
  balance numeric not null,
  notes text,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp
);

create table if not exists recurring_bills (
  id text primary key,
  name text not null,
  expected_amount numeric not null,
  due_day integer not null,
  frequency text not null,
  category_id text references categories(id),
  account_id text references accounts(id),
  is_shared integer not null default 0,
  split_count integer,
  active integer not null default 1,
  notes text,
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp
);

create table if not exists user_settings (
  id text primary key,
  setting_key text not null unique,
  setting_value text not null,
  notes text,
  updated_at text not null default current_timestamp
);

create index if not exists idx_transactions_date on transactions(transaction_date);
create index if not exists idx_transactions_category on transactions(category_id);
create index if not exists idx_transactions_needs_review on transactions(needs_review);
create index if not exists idx_transactions_source_import on transactions(source_import_id);
create index if not exists idx_rules_priority on categorization_rules(active, priority desc, id asc);
