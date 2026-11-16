-- ふたり暮らしアプリのテーブル定義
-- Supabase の SQL Editor にこのファイル全体を貼り付けて実行してください。
-- （ローカル開発では SQLite に対して自動で実行されます）
-- 日付は 'YYYY-MM-DD'、日時は ISO 形式の文字列、真偽値は 0/1 で保存します。

create table if not exists households (
  id text primary key,
  name text not null,
  invite_code text not null unique,
  created_at text not null
);

create table if not exists users (
  id text primary key,
  email text not null unique,
  display_name text not null default '',
  color text not null default 'anzu',
  household_id text references households(id),
  ical_token text not null unique,
  password_hash text,
  created_at text not null
);

create table if not exists chores (
  id text primary key,
  household_id text not null references households(id),
  name text not null,
  freq_type text not null default 'daily',
  weekdays text not null default '',
  interval_days integer not null default 1,
  start_date text not null,
  assignee_id text references users(id),
  active integer not null default 1,
  created_at text not null
);

create table if not exists chore_logs (
  id text primary key,
  chore_id text not null references chores(id) on delete cascade,
  household_id text not null references households(id),
  due_date text not null,
  done_by text not null references users(id),
  done_at text not null,
  unique (chore_id, due_date)
);

create table if not exists recipes (
  id text primary key,
  household_id text not null references households(id),
  name text not null,
  url text not null default '',
  ingredients text not null default '',
  memo text not null default '',
  created_at text not null
);

create table if not exists meals (
  id text primary key,
  household_id text not null references households(id),
  day text not null,
  slot text not null,
  title text not null default '',
  recipe_id text references recipes(id) on delete set null,
  unique (household_id, day, slot)
);

create table if not exists shopping_items (
  id text primary key,
  household_id text not null references households(id),
  name text not null,
  qty text not null default '',
  category text not null default 'other',
  done integer not null default 0,
  done_at text,
  added_by text references users(id),
  meal_id text references meals(id) on delete set null,
  created_at text not null
);

create table if not exists tasks (
  id text primary key,
  household_id text not null references households(id),
  title text not null,
  assignee_id text references users(id),
  due_date text,
  memo text not null default '',
  done integer not null default 0,
  done_by text references users(id),
  done_at text,
  created_at text not null
);

create table if not exists pantry_items (
  id text primary key,
  household_id text not null references households(id),
  name text not null,
  qty text not null default '',
  expires_on text,
  created_at text not null
);

create table if not exists events (
  id text primary key,
  household_id text not null references households(id),
  owner_id text references users(id),
  title text not null,
  day text not null,
  start_time text not null default '',
  end_time text not null default '',
  kind text not null default 'event',
  visibility text not null default 'full',
  repeat_type text not null default 'none',
  weekdays text not null default '',
  memo text not null default '',
  created_at text not null
);

create table if not exists notes (
  id text primary key,
  household_id text not null references households(id),
  title text not null,
  body text not null default '',
  category text not null default 'other',
  updated_at text not null
);

create table if not exists push_subscriptions (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at text not null
);

create index if not exists idx_chores_hh on chores (household_id);
create index if not exists idx_chore_logs_hh on chore_logs (household_id, due_date);
create index if not exists idx_shopping_hh on shopping_items (household_id, done);
create index if not exists idx_meals_hh on meals (household_id, day);
create index if not exists idx_tasks_hh on tasks (household_id, done);
create index if not exists idx_events_hh on events (household_id, day);

-- [postgres-only] ここから下は Supabase 専用です。
-- アプリはサーバーからデータベースに直接つなぐので、Supabase の公開 API
-- （anon キー）からは一切読めないよう、全テーブルで RLS を有効にします。
alter table households enable row level security;
alter table users enable row level security;
alter table chores enable row level security;
alter table chore_logs enable row level security;
alter table recipes enable row level security;
alter table meals enable row level security;
alter table shopping_items enable row level security;
alter table tasks enable row level security;
alter table pantry_items enable row level security;
alter table events enable row level security;
alter table notes enable row level security;
alter table push_subscriptions enable row level security;
