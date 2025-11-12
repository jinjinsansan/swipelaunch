create table if not exists creator_followers (
    id uuid primary key default gen_random_uuid(),
    creator_id uuid not null references users(id) on delete cascade,
    follower_id uuid not null references users(id) on delete cascade,
    notify_email boolean not null default true,
    last_notified_at timestamptz,
    created_at timestamptz not null default timezone('utc'::text, now()),
    updated_at timestamptz not null default timezone('utc'::text, now()),
    unique (creator_id, follower_id)
);

create index if not exists idx_creator_followers_creator on creator_followers(creator_id);
create index if not exists idx_creator_followers_follower on creator_followers(follower_id);

create or replace function trg_creator_followers_updated_at()
returns trigger as $$
begin
    new.updated_at = timezone('utc'::text, now());
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_creator_followers_updated_at on creator_followers;
create trigger trg_creator_followers_updated_at
before update on creator_followers
for each row
execute procedure trg_creator_followers_updated_at();

alter table operator_messages
    add column if not exists automated boolean not null default false,
    add column if not exists related_note_id uuid,
    add column if not exists related_creator_id uuid,
    add column if not exists metadata jsonb default '{}'::jsonb;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'operator_messages_related_note_id_fkey'
    ) then
        alter table operator_messages
            add constraint operator_messages_related_note_id_fkey
                foreign key (related_note_id) references notes(id) on delete set null;
    end if;
end $$;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'operator_messages_related_creator_id_fkey'
    ) then
        alter table operator_messages
            add constraint operator_messages_related_creator_id_fkey
                foreign key (related_creator_id) references users(id) on delete set null;
    end if;
end $$;

create index if not exists idx_operator_messages_related_note on operator_messages(related_note_id);
create index if not exists idx_operator_messages_related_creator on operator_messages(related_creator_id);
