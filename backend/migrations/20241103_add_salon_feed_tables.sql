-- Create tables for salon community feed (posts, comments, likes)

CREATE TABLE IF NOT EXISTS salon_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    body TEXT NOT NULL,
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_salon_posts_salon ON salon_posts(salon_id);
CREATE INDEX IF NOT EXISTS idx_salon_posts_user ON salon_posts(user_id);
CREATE INDEX IF NOT EXISTS idx_salon_posts_published ON salon_posts(is_published);

DROP TRIGGER IF EXISTS trg_salon_posts_updated_at ON salon_posts;
CREATE TRIGGER trg_salon_posts_updated_at
BEFORE UPDATE ON salon_posts
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();


CREATE TABLE IF NOT EXISTS salon_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES salon_posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    parent_id UUID REFERENCES salon_comments(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_salon_comments_post ON salon_comments(post_id);
CREATE INDEX IF NOT EXISTS idx_salon_comments_user ON salon_comments(user_id);
CREATE INDEX IF NOT EXISTS idx_salon_comments_parent ON salon_comments(parent_id);

DROP TRIGGER IF EXISTS trg_salon_comments_updated_at ON salon_comments;
CREATE TRIGGER trg_salon_comments_updated_at
BEFORE UPDATE ON salon_comments
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();


CREATE TABLE IF NOT EXISTS salon_post_likes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES salon_posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (post_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_salon_post_likes_post ON salon_post_likes(post_id);
CREATE INDEX IF NOT EXISTS idx_salon_post_likes_user ON salon_post_likes(user_id);


ALTER TABLE salon_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE salon_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE salon_post_likes ENABLE ROW LEVEL SECURITY;
