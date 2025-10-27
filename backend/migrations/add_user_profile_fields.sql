-- ユーザープロフィール拡張用のカラム追加

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS bio TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS sns_url TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS line_url TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS profile_image_url TEXT;

COMMENT ON COLUMN users.bio IS '公開プロフィールで表示する自己紹介文';
COMMENT ON COLUMN users.sns_url IS '公開プロフィールに表示するSNSリンク';
COMMENT ON COLUMN users.line_url IS '公開プロフィールに表示する公式LINEリンク';
COMMENT ON COLUMN users.profile_image_url IS '公開プロフィールに表示するアイコン画像URL';
