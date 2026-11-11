-- Accounts: saved bills, notes, recently viewed, and the daily digest.
--
-- Sign-in is Supabase Auth with a one-time email code (no passwords). Every table a user
-- writes to has row level security keyed to auth.uid(), so the public browser key can only
-- ever read or change the signed-in person's own rows. bill_status is public and written
-- only by the refresh workflow with the service role key (scripts/sync_status.py).

-- ---------- Profiles ----------
create table if not exists public.profiles (
  id             uuid primary key references auth.users (id) on delete cascade,
  display_name   text check (char_length(display_name) <= 80),
  role           text check (role in ('staff', 'lobbyist', 'advocate', 'agency', 'press', 'other')),
  organization   text check (char_length(organization) <= 120),
  digest_enabled boolean not null default true,
  last_digest_at timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- One profile per new account, made by the database so the browser never has to
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------- Watchlist ----------
-- session is the first year of the two-year session (2025 for 2025-26), bill_id like "AB1234"
create table if not exists public.watchlist (
  user_id  uuid not null references auth.users (id) on delete cascade default auth.uid(),
  session  smallint not null check (session between 1989 and 2100),
  bill_id  text not null check (bill_id ~ '^[A-Z]{2,5}[0-9]{1,5}$'),
  added_at timestamptz not null default now(),
  primary key (user_id, session, bill_id)
);

-- ---------- Notes ----------
create table if not exists public.notes (
  id         bigint generated always as identity primary key,
  user_id    uuid not null references auth.users (id) on delete cascade default auth.uid(),
  session    smallint not null check (session between 1989 and 2100),
  bill_id    text not null check (bill_id ~ '^[A-Z]{2,5}[0-9]{1,5}$'),
  body       text not null check (char_length(body) between 1 and 10000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists notes_user_bill on public.notes (user_id, session, bill_id);

-- ---------- Recently viewed ----------
-- One row per person and bill; viewing again moves it to the top and counts the visit
create table if not exists public.history (
  user_id   uuid not null references auth.users (id) on delete cascade default auth.uid(),
  session   smallint not null check (session between 1989 and 2100),
  bill_id   text not null check (bill_id ~ '^[A-Z]{2,5}[0-9]{1,5}$'),
  viewed_at timestamptz not null default now(),
  views     integer not null default 1,
  primary key (user_id, session, bill_id)
);
create index if not exists history_recent on public.history (user_id, viewed_at desc);

-- Record a view in one call (insert, or bump the time and count)
create or replace function public.record_view(p_session smallint, p_bill text) returns void
language sql security invoker set search_path = public as $$
  insert into public.history (user_id, session, bill_id) values (auth.uid(), p_session, p_bill)
  on conflict (user_id, session, bill_id) do update set viewed_at = now(), views = public.history.views + 1;
$$;

-- ---------- Current status of each bill (public, written by the refresh workflow) ----------
create table if not exists public.bill_status (
  session          smallint not null,
  bill_id          text not null,
  title            text,
  author           text,
  outcome          text,              -- signed, vetoed, not_enacted, pending
  last_action      text,              -- the latest line of the official bill history
  last_action_date date,
  odds             real,              -- latest tracked chance of being signed, 0 to 1
  odds_intro       real,              -- the same at introduction
  changed_at       timestamptz not null default now(),   -- when anything above last changed
  primary key (session, bill_id)
);
create index if not exists bill_status_changed on public.bill_status (changed_at desc);

-- changed_at moves only when the bill actually changed, so the digest reports real news
create or replace function public.bill_status_touch() returns trigger
language plpgsql as $$
begin
  if tg_op = 'UPDATE' and (new.outcome, new.last_action, new.last_action_date, new.odds)
       is not distinct from (old.outcome, old.last_action, old.last_action_date, old.odds) then
    new.changed_at := old.changed_at;
  else
    new.changed_at := now();
  end if;
  return new;
end $$;
drop trigger if exists bill_status_touch on public.bill_status;
create trigger bill_status_touch before insert or update on public.bill_status
  for each row execute function public.bill_status_touch();

-- ---------- Limits ----------
-- Keep any one account from filling the database
create or replace function public.enforce_row_cap() returns trigger
language plpgsql security definer set search_path = public as $$
declare n integer; cap integer := tg_argv[0]::integer;
begin
  execute format('select count(*) from public.%I where user_id = $1', tg_table_name) into n using new.user_id;
  if n >= cap then
    raise exception 'limit reached: % rows in %', cap, tg_table_name using errcode = 'check_violation';
  end if;
  return new;
end $$;
drop trigger if exists watchlist_cap on public.watchlist;
create trigger watchlist_cap before insert on public.watchlist for each row execute function public.enforce_row_cap('2000');
drop trigger if exists notes_cap on public.notes;
create trigger notes_cap before insert on public.notes for each row execute function public.enforce_row_cap('5000');

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at := now(); return new; end $$;
drop trigger if exists notes_touch on public.notes;
create trigger notes_touch before update on public.notes for each row execute function public.touch_updated_at();

-- The browser may edit name, role, organization and the digest switch; last_digest_at and
-- created_at belong to the server (the digest job runs as service_role)
create or replace function public.profiles_guard() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  if coalesce(auth.role(), '') <> 'service_role' then
    new.last_digest_at := old.last_digest_at;
    new.created_at := old.created_at;
    new.id := old.id;
  end if;
  return new;
end $$;
drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles for each row execute function public.profiles_guard();

-- ---------- Row level security ----------
alter table public.profiles    enable row level security;
alter table public.watchlist   enable row level security;
alter table public.notes       enable row level security;
alter table public.history     enable row level security;
alter table public.bill_status enable row level security;

drop policy if exists "own profile" on public.profiles;
create policy "own profile" on public.profiles for all to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "own watchlist" on public.watchlist;
create policy "own watchlist" on public.watchlist for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own notes" on public.notes;
create policy "own notes" on public.notes for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own history" on public.history;
create policy "own history" on public.history for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "anyone reads bill status" on public.bill_status;
create policy "anyone reads bill status" on public.bill_status for select to anon, authenticated using (true);

-- ---------- Delete my account ----------
-- Removes the sign-in and, through the cascades, every saved bill, note and view
create or replace function public.delete_my_account() returns void
language plpgsql security definer set search_path = public, auth as $$
begin
  if auth.uid() is null then raise exception 'not signed in'; end if;
  delete from auth.users where id = auth.uid();
end $$;
revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;
revoke all on function public.record_view(smallint, text) from public, anon;
grant execute on function public.record_view(smallint, text) to authenticated;
