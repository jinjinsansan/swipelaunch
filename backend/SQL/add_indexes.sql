-- Supabase index recommendations (run via SQL editor or migration tool)

-- Notes: speed up author/status queries and slug lookups
create index if not exists idx_notes_author_status on public.notes (author_id, status);
create index if not exists idx_notes_slug on public.notes (slug);

-- Note purchases: accelerate author sales aggregation and date filtering
create index if not exists idx_note_purchases_note_id_purchased on public.note_purchases (note_id, purchased_at);

-- Sales-related tables: membership lookups by salon/status
create index if not exists idx_salon_memberships_salon_status on public.salon_memberships (salon_id, status);

-- Point transactions: faster history retrieval by user + type + time
create index if not exists idx_point_transactions_user_type_time on public.point_transactions (user_id, transaction_type, created_at desc);

-- Payment orders: support seller dashboard revenue aggregation
create index if not exists idx_payment_orders_seller_created on public.payment_orders (seller_id, created_at desc);
