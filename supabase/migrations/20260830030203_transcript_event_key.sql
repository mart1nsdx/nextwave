-- Transcript integrity: the event key stops depending on a counter.
--
-- unique (case_id, track, sequence_number) made sequence_number load-bearing: a segment
-- was identified by *where it sat in a count*, not by what it says. Two writers seeding
-- the same counter — or one restart re-reading it — could hand two different segments the
-- same number, and the second one was then swallowed by an ignore_duplicates upsert with
-- no error at all. Evidence disappearing silently is the worst shape this bug can take.
--
-- The key is now content-addressed (app/domain/models.py:build_event_key): a redelivered
-- segment produces the same key because it says the same thing at the same instant.
-- sequence_number survives as an ordering hint only, so the constraint has to go.
--
-- Named constraint: the unique was declared inline in 20260829125514_create_call_transcripts.sql
-- as `unique (case_id, track, sequence_number)`, so PostgreSQL derived the name
-- <table>_<columns>_key — 56 characters, below the 63-byte identifier limit, therefore not
-- truncated. `alter table call_cases rename to calls` (20260830024256) renames a table, not
-- the constraints of other tables, so the name is unchanged.

alter table public.call_transcript_events
    drop constraint call_transcript_events_case_id_track_sequence_number_key;

create index call_transcript_events_case_order_idx
    on public.call_transcript_events (case_id, audio_offset_ms, sequence_number, created_at);

-- A barge-in turn is a turn the counterparty actually heard the start of, and it is
-- precisely the turn a judge will create. It used to be written nowhere. `interrupted`
-- marks a reply that was cut mid-generation: the text is what was handed to the
-- synthesizer, never more, so the agent can never be shown claiming something the other
-- side never heard.
alter table public.call_transcript_events
    add column if not exists interrupted boolean not null default false;

-- Denormalised from the CallBinding at write time so "show me every piece of evidence for
-- operation X" is one indexed read instead of a join through calls on every dashboard
-- load. Nullable because the binding is resolved before the session is built and that
-- plumbing does not exist yet; a row written without it is still valid evidence.
alter table public.call_transcript_events
    add column if not exists operation_id uuid references public.operations(id),
    add column if not exists rfq_id uuid references public.rfqs(id);

create index call_transcript_events_operation_idx
    on public.call_transcript_events (operation_id, audio_offset_ms);
create index call_transcript_events_rfq_idx
    on public.call_transcript_events (rfq_id, audio_offset_ms);

comment on column public.call_transcript_events.sequence_number is
    'Ordering hint within a call. NOT an identity: the event key is content-addressed.';
comment on column public.call_transcript_events.interrupted is
    'The reply was cut mid-generation. Text is what reached the synthesizer, never more.';
