# Accounts: setup and how it works

Accounts give each person a watchlist and private notes that follow them to any device, a
list of recently viewed bills, and an optional email each weekday morning with only the
watched bills that changed. Signed out, the site works exactly as before, with the
watchlist kept in the browser.

## Pieces

| Piece | What it does |
| --- | --- |
| `supabase/migrations/20261111120000_accounts.sql` | Tables `profiles`, `watchlist`, `notes`, `history`, `bill_status`, with row level security so the public browser key reaches only the signed-in person's rows. Row caps per account, account deletion, a view counter. Safe to run twice. |
| `site/account.js` | Sign-in with a 6-digit email code, session refresh, and small helpers for each table. No library. |
| `site/account.html` | "My desk": watchlist with latest action and odds, notes, recently viewed, digest settings, CSV downloads, sign out, delete account. |
| `site/index.html` | Watch this bill saves to the account when signed in (bills saved in the browser join the account on sign-in), private notes under each bill, views recorded. |
| `scripts/sync_status.py` | Run by the refresh workflow: writes each current bill's latest action, outcome and odds to `bill_status`. Skips quietly until the secrets exist. |
| `supabase/functions/digest/` | The weekday email. Sends nothing to a person whose bills didn't move. One-click unsubscribe. |

Why a code and not a magic link: many government and firm mail systems open every link in
an email to scan it, which uses up a one-time link before the person clicks it.

## Switching it on (one time)

1. **Database.** In the Supabase project (`taiehocnlzoscniyeyyk`), run the migration:
   `supabase db push`, or paste the file into the SQL editor.
2. **Sign-in emails.** Authentication > Emails > "Magic Link" template: make the body show
   the code, for example `Your Capitol Odds code is {{ .Token }}. It works for one hour.`
   Subject: `Your Capitol Odds sign-in code`.
3. **Send mail from your domain.** Supabase's built-in mail server allows only a few emails an
   hour and is for testing. Create a Resend account, verify `capitolodds.com` (add the DKIM,
   SPF and return-path records it lists in Namecheap DNS), then set Authentication > SMTP to
   Resend (`smtp.resend.com`, port 465, user `resend`, password = a Resend API key), sender
   `Capitol Odds <signin@capitolodds.com>`.
4. **Allowed sites.** Authentication > URL Configuration: Site URL `https://capitolodds.com`,
   and add `https://www.capitolodds.com`.
5. **Status sync.** GitHub repository > Settings > Secrets and variables > Actions: add
   `SUPABASE_URL` (`https://taiehocnlzoscniyeyyk.supabase.co`) and
   `SUPABASE_SERVICE_ROLE_KEY` (Project Settings > API > service_role). Never put the
   service role key in the site.
6. **Digest function.**
   ```bash
   supabase secrets set RESEND_API_KEY=... DIGEST_CRON_SECRET=$(openssl rand -hex 24) \
     DIGEST_FROM="Capitol Odds <digest@capitolodds.com>"
   supabase functions deploy digest --no-verify-jwt
   ```
7. **Schedule it.** In the SQL editor (enable the `pg_cron` and `pg_net` extensions first),
   using the same secret as step 6:
   ```sql
   select cron.schedule('daily-digest', '30 14 * * 1-5', $$
     select net.http_post(
       url := 'https://taiehocnlzoscniyeyyk.supabase.co/functions/v1/digest',
       headers := jsonb_build_object('x-digest-secret', '<DIGEST_CRON_SECRET>', 'Content-Type', 'application/json'),
       body := '{}'::jsonb);
   $$);
   ```
   14:30 UTC is 6:30 a.m. Pacific in winter and 7:30 a.m. in summer. The data refresh runs
   at 12:17 UTC on weekdays, so the digest always reads that morning's data.

## Checking it

- `pytest -q tests/test_accounts.py`: every table has row level security tied to the
  signed-in person, the sync sends clean rows, and the digest reports only changed bills.
- After step 1, sign in on the live site with a test address, watch a bill, add a note,
  then check in the Supabase table editor that the rows carry your user id.
- After step 7, run the function once by hand with the secret header and check the log.

## Limits

- `bill_status` holds the latest action from the bulk export, which posts once a day.
  Hearing dates and agendas aren't in the export; adding the Assembly and Senate daily file
  is the next step for a calendar.
- The digest compares each bill against the time of the person's last digest. The first
  digest after signing up lists every watched bill with a known status.
