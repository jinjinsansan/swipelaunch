"""Mailgun設定診断スクリプト - 本番環境で実行してください"""

import os
from app.config import settings
from app.services import mailgun

print("=" * 60)
print("Mailgun設定診断")
print("=" * 60)

print("\n【環境変数】")
print(f"MAILGUN_API_KEY: {'設定済み' if os.getenv('MAILGUN_API_KEY') else '未設定'}")
print(f"MAILGUN_DOMAIN: {os.getenv('MAILGUN_DOMAIN') or '未設定'}")
print(f"MAILGUN_DEFAULT_FROM_EMAIL: {os.getenv('MAILGUN_DEFAULT_FROM_EMAIL') or '未設定'}")
print(f"REDIS_URL: {'設定済み' if os.getenv('REDIS_URL') else '未設定'}")

print("\n【設定値】")
print(f"mailgun_api_key: {'設定済み' if settings.mailgun_api_key else '未設定'}")
print(f"mailgun_domain: {settings.mailgun_domain or '未設定'}")
print(f"mailgun_default_from_email: {settings.mailgun_default_from_email or '未設定'}")
print(f"redis_url: {'設定済み' if settings.redis_url else '未設定'}")

print("\n【Mailgun状態】")
print(f"is_configured(): {mailgun.is_configured()}")

if mailgun.is_configured():
    print("\n✅ Mailgunは設定されています")
else:
    print("\n❌ Mailgunが正しく設定されていません")
    print("   MAILGUN_API_KEY と MAILGUN_DOMAIN を環境変数に設定してください")

print("\n【データベース確認】")
print("以下のSQLをSupabaseで実行して、実際のメール送信状況を確認してください：")
print("""
-- 購入通知のメール送信状況
SELECT 
    om.category,
    om.created_at,
    COUNT(*) as total_recipients,
    COUNT(omr.email_sent_at) as emails_sent,
    COUNT(*) - COUNT(omr.email_sent_at) as emails_not_sent
FROM operator_messages om
JOIN operator_message_recipients omr ON om.id = omr.message_id
WHERE om.category IN ('purchase', 'sales')
AND om.created_at > NOW() - INTERVAL '7 days'
GROUP BY om.category, om.created_at
ORDER BY om.created_at DESC
LIMIT 10;

-- フォロワー通知のメール送信状況
SELECT 
    om.category,
    om.created_at,
    COUNT(*) as total_recipients,
    COUNT(omr.email_sent_at) as emails_sent,
    COUNT(*) - COUNT(omr.email_sent_at) as emails_not_sent
FROM operator_messages om
JOIN operator_message_recipients omr ON om.id = omr.message_id
WHERE om.category IN ('note_publication', 'lp_publication', 'salon_publication')
AND om.created_at > NOW() - INTERVAL '7 days'
GROUP BY om.category, om.created_at
ORDER BY om.created_at DESC
LIMIT 10;
""")

print("=" * 60)
