-- Fixes a deadlock in the mandate versioning added in 20260829165921, found by trying to
-- raise a cap on the seed data.
--
-- The old design used one column for two jobs: superseded_by was both the LINK to the
-- replacement and the definition of "active" (via `where superseded_by is null`). That
-- makes supersession impossible in either order:
--
--   insert v2 first  -> two rows with superseded_by null -> unique index violation
--   update v1 first  -> superseded_by points at a v2 that does not exist -> FK violation
--
-- A deferrable constraint would fix it, but Postgres cannot defer a PARTIAL unique index,
-- so the fix is to separate the two jobs. status defines active; superseded_by stays as
-- the link and is filled in last:
--
--   update v1 set status = 'superseded'   -- frees the index, touches no FK
--   insert v2 with status = 'active'      -- index is free
--   update v1 set superseded_by = v2      -- FK now satisfiable
--
-- Worth stating plainly: the constraint was right and the schema was wrong. The database
-- refused a state that would have left two live mandates on one operation, which is
-- exactly its job -- it just also refused the legitimate path, and that is a schema bug.
-- D23/D25 require mandate mutation from the dashboard, so this had to work.

alter table public.mandates
    add column status text not null default 'active'
        check (status in ('active', 'superseded', 'expired', 'revoked'));

update public.mandates set status = 'superseded' where superseded_by is not null;

drop index if exists public.mandates_one_active_per_operation_idx;

create unique index mandates_one_active_per_operation_idx
    on public.mandates (operation_id) where status = 'active';

comment on column public.mandates.status is
    'Lifecycle state. The partial unique index keys on this, not on superseded_by, so that a new version can be inserted before the old row points at it.';
