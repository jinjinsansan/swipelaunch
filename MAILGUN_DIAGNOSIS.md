# Mailgun メール配信問題 診断・修正ガイド

## 問題の概要
フォロワー通知システムで、運営からのお知らせ受信箱には通知が届くが、実際のメール配信がされない。

## 根本原因（95%確信）
**Mailgunの設定が不完全または未設定**

### 証拠
1. `deliver_bulk_email_sync()` に設定チェックがなく、`mailgun_domain` が `None` の場合でもエラーを出さない
2. フォロワー通知と購入通知の実装が異なり、フォロワー通知だけが失敗する可能性がある
3. `send_bulk_email_async()` はキューに入れた時点で成功とみなし、実際の送信確認をしていない

## 診断手順

### ステップ1: 本番環境でMailgun設定を確認

```bash
# Renderダッシュボードまたは本番環境で以下を確認
cd /path/to/backend
python diagnosis_script.py
```

期待される出力：
```
Mailgun設定診断
============================================================

【環境変数】
MAILGUN_API_KEY: 設定済み
MAILGUN_DOMAIN: your-domain.mailgun.org
MAILGUN_DEFAULT_FROM_EMAIL: no-reply@your-domain.com
REDIS_URL: 設定済み

【設定値】
mailgun_api_key: 設定済み
mailgun_domain: your-domain.mailgun.org
mailgun_default_from_email: no-reply@your-domain.com
redis_url: 設定済み

【Mailgun状態】
is_configured(): True

✅ Mailgunは設定されています
```

**もし `is_configured(): False` の場合、これが根本原因です。**

### ステップ2: データベースで実際のメール送信状況を確認

Supabase SQLエディタで以下を実行：

```sql
-- 購入通知のメール送信状況（過去7日間）
SELECT 
    om.category,
    om.created_at,
    om.title,
    COUNT(*) as total_recipients,
    COUNT(omr.email_sent_at) as emails_sent,
    COUNT(*) - COUNT(omr.email_sent_at) as emails_not_sent
FROM operator_messages om
JOIN operator_message_recipients omr ON om.id = omr.message_id
WHERE om.category IN ('purchase', 'sales')
AND om.created_at > NOW() - INTERVAL '7 days'
GROUP BY om.id, om.category, om.created_at, om.title
ORDER BY om.created_at DESC
LIMIT 10;

-- フォロワー通知のメール送信状況（過去7日間）
SELECT 
    om.category,
    om.created_at,
    om.title,
    COUNT(*) as total_recipients,
    COUNT(omr.email_sent_at) as emails_sent,
    COUNT(*) - COUNT(omr.email_sent_at) as emails_not_sent
FROM operator_messages om
JOIN operator_message_recipients omr ON om.id = omr.message_id
WHERE om.category IN ('note_publication', 'lp_publication', 'salon_publication')
AND om.created_at > NOW() - INTERVAL '7 days'
GROUP BY om.id, om.category, om.created_at, om.title
ORDER BY om.created_at DESC
LIMIT 10;
```

**期待される結果:**
- `emails_sent` = `total_recipients` （すべてのメールが送信されている）
- もし `emails_not_sent > 0` の場合、メール配信に失敗しています

### ステップ3: 本番環境ログを確認

Renderログまたはアプリケーションログで以下を検索：

```
# Mailgun関連のエラー
"Mailgun is not configured"
"Mailgun send skipped"
"Mailgun request failed"
"Mailgun rejected request"

# フォロワー通知関連
"Attempting to send follower notification"
"send_bulk_email (sync) result"
"send_bulk_email_async result"
"Mailgun did not accept any recipients"
```

## 修正手順

### 修正1: Mailgun設定を追加（最優先）

Renderの環境変数に以下を追加：

```bash
MAILGUN_API_KEY=key-xxxxxxxxxxxxxxxxxxxxxxxxxx
MAILGUN_DOMAIN=your-domain.mailgun.org
MAILGUN_DEFAULT_FROM_EMAIL=no-reply@your-domain.com
MAILGUN_DEFAULT_FROM_NAME=D-swipe 運営
MAILGUN_DEFAULT_REPLY_TO=info@dlogicai.com
```

**Mailgunアカウントの確認方法:**
1. https://app.mailgun.com にログイン
2. "Sending" > "Domain settings" でドメインを確認
3. "API" セクションでAPIキーを取得

### 修正2: コード修正を適用

すでに以下の修正を適用しました：

1. **`mailgun.py`**: `deliver_bulk_email_sync()` に設定チェックを追加
2. **`note_notifications.py`**: 詳細なログを追加

修正をコミット＆プッシュしてください。

### 修正3: Redis設定を確認（オプション）

非同期キュー（RQ）を使用する場合、Redis設定も必要：

```bash
REDIS_URL=redis://your-redis-host:6379
```

**注意:** Redisが設定されていない場合、`send_bulk_email_async()` は自動的に同期送信にフォールバックします。

## 検証手順

### 1. 設定確認後、テスト通知を送信

```python
# バックエンドコンソールで実行
from app.services import mailgun
from app.services.mailgun import MailgunRecipient
from app.config import settings

# 設定確認
print(f"Mailgun configured: {mailgun.is_configured()}")
print(f"Domain: {settings.mailgun_domain}")

# テストメール送信
result = mailgun.send_bulk_email(
    subject="Test email from D-swipe",
    text="This is a test email",
    html="<p>This is a test email</p>",
    recipients=[MailgunRecipient(email="your-test@email.com", name="Test User")],
    sender_email=settings.mailgun_default_from_email,
    sender_name="D-swipe Test",
    reply_to=settings.mailgun_default_reply_to,
)

print(f"Accepted recipients: {result}")
```

### 2. 実際のフォロワー通知をテスト

1. テストユーザーでクリエイターをフォロー（メール通知ON）
2. そのクリエイターがノートを公開
3. 以下を確認：
   - オペレーターメッセージ受信箱に通知が届く
   - **実際のメールアドレスにメールが届く** ← これが重要！
   - データベースで `email_sent_at` が記録されている

### 3. ログで詳細を確認

修正後のログ出力例：

```
INFO: Attempting to send follower notification: category=note_publication, recipients=3, mailgun_configured=True
INFO: send_bulk_email (sync) result: accepted=3 recipients
INFO: Updated email_sent_at for 3 recipients
```

もし失敗した場合：

```
ERROR: Mailgun is not configured (API key or domain missing); cannot send email
INFO: send_bulk_email (sync) result: accepted=0 recipients
INFO: Falling back to send_bulk_email_async
INFO: send_bulk_email_async result: accepted=0 recipients
WARNING: Mailgun did not accept any recipients for category note_publication (requested: 3 recipients)
```

## よくある問題と解決策

### Q1: 購入通知は届くが、フォロワー通知は届かない

**A:** 以下を確認：
1. フォロワー通知は複数の受信者に送信するため、バッチ処理の問題がある可能性
2. メール本文のエンコーディング問題（日本語の取り扱い）
3. Mailgunのレート制限

→ ログで `send_bulk_email (sync) result` を確認

### Q2: `is_configured()` は True だが、メールが届かない

**A:** Mailgunダッシュボードで確認：
1. ドメイン検証が完了しているか
2. 送信履歴に配信失敗のログがあるか
3. SPF/DKIM/DMARCレコードが正しく設定されているか

### Q3: ログに "Mailgun rejected request (status=400)" が出る

**A:** リクエストペイロードの問題：
1. `sender_email` がMailgunで許可されたドメインか
2. 受信者のメールアドレスが有効か
3. メール本文が大きすぎないか

## 95%確信の結論

問題の根本原因は以下のいずれか（優先度順）：

1. **Mailgun設定が本番環境で未設定** （最も可能性が高い）
2. Mailgunドメイン検証が未完了
3. `deliver_bulk_email_sync()` の設定チェック不足によるサイレントエラー

**必須の対応:**
- Render環境変数に `MAILGUN_API_KEY` と `MAILGUN_DOMAIN` を設定
- 修正コードをデプロイ
- テスト通知で実際のメール配信を確認

**これで解決しない場合:**
- Mailgunダッシュボードの送信ログを確認
- バックエンドログの全文を共有（Mailgun関連のエラー）
