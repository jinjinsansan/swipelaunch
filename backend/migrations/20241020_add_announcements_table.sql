-- 2024-10-20: 管理者お知らせテーブル追加
CREATE TABLE IF NOT EXISTS announcements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(200) NOT NULL,
  summary VARCHAR(255) NOT NULL,
  body TEXT NOT NULL,
  is_published BOOLEAN DEFAULT TRUE,
  highlight BOOLEAN DEFAULT FALSE,
  published_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_by_email VARCHAR(255),
  created_by_username VARCHAR(100),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_announcements_published_at ON announcements(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_announcements_published ON announcements(is_published);

ALTER TABLE announcements ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Announcements are viewable" ON announcements;
CREATE POLICY "Announcements are viewable" ON announcements
  FOR SELECT USING (true);

DROP POLICY IF EXISTS "Announcements are manageable by service" ON announcements;
CREATE POLICY "Announcements are manageable by service" ON announcements
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
