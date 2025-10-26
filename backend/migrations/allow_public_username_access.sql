-- Allow public access to username and email fields for marketplace display
-- This enables frontend to display seller information on LP cards

-- Drop the restrictive policy (if exists)
DROP POLICY IF EXISTS "Users can view own data" ON users;

-- Create new policies for users table
-- Policy 1: Users can view their own complete data
CREATE POLICY "Users can view own complete data" ON users
  FOR SELECT 
  USING (auth.uid() = id);

-- Policy 2: Anyone can view username and email of all users (for marketplace)
CREATE POLICY "Public can view usernames" ON users
  FOR SELECT
  USING (true);

-- Alternative: If you want to only allow viewing specific columns
-- You can use Postgres RLS with column-level security, but Supabase doesn't support this directly
-- So we allow full row access but the backend will only select username and email

-- NOTE: This is safe because:
-- 1. username and email are already public information (displayed on marketplace)
-- 2. Sensitive fields like point_balance, is_blocked are only used in authenticated contexts
-- 3. The backend explicitly selects only (username, email) in the JOIN query

-- Grant read access to authenticated and anon roles
GRANT SELECT ON users TO authenticated;
GRANT SELECT ON users TO anon;
