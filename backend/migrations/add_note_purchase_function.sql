-- Migration: create transactional function for note purchases

set search_path = public;

create or replace function purchase_note_with_points(p_note_id uuid, p_buyer_id uuid)
returns table (
    purchase_id uuid,
    points_spent integer,
    remaining_points integer,
    purchased_at timestamptz
)
language plpgsql
security definer
as $$
declare
    v_note notes%rowtype;
    v_balance integer;
    v_purchase note_purchases%rowtype;
    v_title text;
begin
    select * into v_note
    from notes
    where id = p_note_id
    for update;

    if not found then
        raise exception using errcode = 'P0002', message = '記事が見つかりません';
    end if;

    if v_note.status <> 'published' then
        raise exception using errcode = 'P0001', message = '公開されていない記事です';
    end if;

    if not coalesce(v_note.is_paid, false) then
        raise exception using errcode = 'P0001', message = '無料記事の購入は不要です';
    end if;

    if v_note.author_id = p_buyer_id then
        raise exception using errcode = 'P0001', message = '自身の記事は購入できません';
    end if;

    if v_note.price_points is null or v_note.price_points <= 0 then
        raise exception using errcode = 'P0001', message = '記事の価格が設定されていません';
    end if;

    perform 1
    from note_purchases
    where note_id = p_note_id
      and buyer_id = p_buyer_id;
    if found then
        raise exception using errcode = '23505', message = '既に購入済みです';
    end if;

    select point_balance into v_balance
    from users
    where id = p_buyer_id
    for update;

    if not found then
        raise exception using errcode = 'P0002', message = 'ユーザーが見つかりません';
    end if;

    if v_balance < v_note.price_points then
        raise exception using errcode = 'P0001', message = 'ポイントが不足しています';
    end if;

    v_balance := v_balance - v_note.price_points;

    update users
    set point_balance = v_balance
    where id = p_buyer_id;

    insert into note_purchases (note_id, buyer_id, points_spent)
    values (p_note_id, p_buyer_id, v_note.price_points)
    returning * into v_purchase;

    v_title := coalesce(v_note.title, 'NOTE');

    insert into point_transactions (user_id, transaction_type, amount, related_note_id, description)
    values (
        p_buyer_id,
        'note_purchase',
        -v_note.price_points,
        p_note_id,
        format('記事「%s」を購入しました', v_title)
    );

    return query select v_purchase.id, v_purchase.points_spent, v_balance, v_purchase.purchased_at;
end;
$$;

revoke all on function purchase_note_with_points(uuid, uuid) from public;
grant execute on function purchase_note_with_points(uuid, uuid) to authenticated;
grant execute on function purchase_note_with_points(uuid, uuid) to service_role;
