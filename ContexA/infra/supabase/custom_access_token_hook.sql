-- ContexA requires a signed email_verified claim before linking a Supabase
-- identity to an existing ContexA account. Supabase's standard access-token
-- claim set does not guarantee this claim, so this hook derives it from the
-- authoritative auth.users.email_confirmed_at field.
--
-- After applying, enable this function under Supabase Dashboard:
-- Authentication -> Hooks -> Custom Access Token (before issuing the JWT).

create or replace function public.contexa_custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  claims jsonb;
  verified boolean := false;
  auth_user_id uuid;
begin
  auth_user_id := (event ->> 'user_id')::uuid;

  select (u.email_confirmed_at is not null)
    into verified
    from auth.users as u
   where u.id = auth_user_id;

  claims := coalesce(event -> 'claims', '{}'::jsonb);
  claims := jsonb_set(claims, '{email_verified}', to_jsonb(coalesce(verified, false)), true);

  return jsonb_set(event, '{claims}', claims, true);
end;
$$;

-- Supabase Auth invokes the hook as supabase_auth_admin. Restrict direct
-- execution by application/browser roles. Validate grants against your
-- project's current Auth Hook setup before enabling in production.
grant usage on schema public to supabase_auth_admin;
grant execute on function public.contexa_custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.contexa_custom_access_token_hook(jsonb) from public, anon, authenticated;
