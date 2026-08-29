# Supabase migrations

This directory is the source of truth for database schema changes. Do not run
schema-changing SQL directly in the hosted SQL Editor after this workflow is
enabled: direct edits bypass Git migration history and cause divergent schemas.

## Included schema

`20260829125514_create_call_transcripts.sql` creates:

- `call_cases`: one auditable case per Twilio `CallSid`.
- `call_transcript_events`: append-only partial or final STT text, keyed
  idempotently and linked to a millisecond audio offset.

Neither table records a commitment. Transcript evidence must still pass through
the policy, readback, confirmation, recap, and ledger flow before any commitment
can exist.

## First deployment

The GitHub repository stores this SQL; it does not connect itself to Supabase.
An authorized teammate must run the following from the repository root:

```bash
supabase login
supabase link --project-ref <your-project-ref>
supabase db pull                 # only if the remote already has manual schema changes
supabase db push --dry-run
supabase db push
```

The `project-ref` is the segment in the Supabase dashboard URL after
`/project/`. `supabase link` / `db push` use a Supabase login and database
credentials; they do not use the publishable or service-role API keys.

Run only one `db push` at a time for this shared hackathon project. The backend
gets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from `backend/.env`; keep
both out of Git. The service-role key is backend-only and bypasses RLS.
