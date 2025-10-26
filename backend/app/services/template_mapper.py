"""
テンプレートメタデータとビジネスロジックのマッピング

フロントエンドの新しいテンプレートライブラリに完全対応
"""
from typing import Dict, List, Optional


# ヒーローブロックのメタデータ（動画背景）
HERO_VIDEO_TEMPLATES = [
    {
        "id": "top-hero-landing",
        "name": "ヒーロー（情報鮮度）",
        "description": "TOPページのヒーローセクション。スピード感と鮮度を訴求",
        "videoUrl": "/videos/pixta.mp4",
        "keywords": ["情報", "スピード", "鮮度", "最新", "汎用"],
        "suitable_for": ["全般", "情報商材", "オンライン講座"],
        "theme_match": ["urgent_red", "power_blue"],
    },
    {
        "id": "top-hero-book-flip",
        "name": "ヒーロー（知識を書籍で紐解く）",
        "description": "静かな書斎で本をめくる映像。研究系・教材系に最適",
        "videoUrl": "/videos/hero-book-flip.mp4",
        "keywords": ["書籍", "知識", "学習", "教材", "研究", "静か"],
        "suitable_for": ["教育", "資格", "英語", "学習教材"],
        "theme_match": ["power_blue"],
    },
    {
        "id": "top-hero-couple",
        "name": "ヒーロー（カップルの未来設計）",
        "description": "寄り添うカップルの映像。恋愛・ライフスタイル商材に合う",
        "videoUrl": "/videos/hero-couple.mp4",
        "keywords": ["カップル", "恋愛", "結婚", "二人", "ライフスタイル"],
        "suitable_for": ["恋愛", "モテ術", "婚活", "ライフスタイル"],
        "theme_match": ["passion_pink"],
    },
    {
        "id": "top-hero-smartphone",
        "name": "ヒーロー（スマホ操作）",
        "description": "スマホ操作の映像。デジタル教材や自動化ツール訴求",
        "videoUrl": "/videos/hero-smartphone.mp4",
        "keywords": ["スマホ", "モバイル", "デジタル", "操作", "アプリ"],
        "suitable_for": ["SNS集客", "デジタルマーケティング", "アプリ"],
        "theme_match": ["power_blue", "urgent_red"],
    },
    {
        "id": "top-hero-night-crossing",
        "name": "ヒーロー（夜の交差点）",
        "description": "都会の交差点。スピード感と勢いを演出",
        "videoUrl": "/videos/hero-night-crossing.mp4",
        "keywords": ["交差点", "都会", "夜", "スピード", "都市"],
        "suitable_for": ["ビジネス", "副業", "マーケティング"],
        "theme_match": ["urgent_red", "gold_premium"],
    },
    {
        "id": "top-hero-night-road",
        "name": "ヒーロー（夜の道路）",
        "description": "光が流れる夜の道路。投資・副業系の緊張感を演出",
        "videoUrl": "/videos/hero-night-road.mp4",
        "keywords": ["道路", "夜", "スピード", "光", "疾走"],
        "suitable_for": ["投資", "FX", "副業", "トレード"],
        "theme_match": ["urgent_red"],
    },
    {
        "id": "top-hero-smoke",
        "name": "ヒーロー（スモーク演出）",
        "description": "幻想的な煙の映像。ブランディング性の高い講座訴求",
        "videoUrl": "/videos/hero-smoke.mp4",
        "keywords": ["煙", "スモーク", "幻想", "ミステリアス", "高級"],
        "suitable_for": ["自己啓発", "コーチング", "高額商品"],
        "theme_match": ["gold_premium"],
    },
    {
        "id": "top-hero-beach",
        "name": "ヒーロー（砂浜と海）",
        "description": "穏やかな波の映像。ライフスタイルやウェルネス訴求",
        "videoUrl": "/videos/hero-beach.mp4",
        "keywords": ["砂浜", "海", "波", "リラックス", "癒し"],
        "suitable_for": ["ウェルネス", "ライフスタイル", "自己啓発"],
        "theme_match": ["power_blue", "passion_pink"],
    },
    {
        "id": "top-hero-downtown",
        "name": "ヒーロー（繁華街の熱量）",
        "description": "繁華街のネオンと人の流れ。エネルギッシュな市場を印象づける",
        "videoUrl": "/videos/hero-downtown.mp4",
        "keywords": ["繁華街", "ネオン", "都市", "人混み", "エネルギー"],
        "suitable_for": ["ビジネス", "マーケティング", "集客"],
        "theme_match": ["urgent_red", "energy_orange"],
    },
    {
        "id": "top-hero-tiger",
        "name": "ヒーロー（虎の咆哮）",
        "description": "虎の迫力ある映像。自己啓発やマインドセット系に響く",
        "videoUrl": "/videos/hero-tiger.mp4",
        "keywords": ["虎", "動物", "迫力", "パワー", "野性"],
        "suitable_for": ["自己啓発", "マインドセット", "コーチング"],
        "theme_match": ["gold_premium", "urgent_red"],
    },
    {
        "id": "top-hero-running-man",
        "name": "ヒーロー（走る男性）",
        "description": "走り抜ける男性の映像。フィットネスや習慣化商材を訴求",
        "videoUrl": "/videos/hero-running-man.mp4",
        "keywords": ["走る", "ランニング", "フィットネス", "運動", "男性"],
        "suitable_for": ["ダイエット", "筋トレ", "フィットネス", "習慣化"],
        "theme_match": ["energy_orange"],
    },
    {
        "id": "top-hero-gold-particles",
        "name": "ヒーロー（金の粒子）",
        "description": "金色の粒子が舞う映像。プレミアムな高額商品を演出",
        "videoUrl": "/videos/hero-gold-particles.mp4",
        "keywords": ["金", "ゴールド", "粒子", "高級", "プレミアム"],
        "suitable_for": ["高額商品", "コンサルティング", "プレミアム講座"],
        "theme_match": ["gold_premium"],
    },
    {
        "id": "top-hero-finance",
        "name": "ヒーロー（金融アドバイザー）",
        "description": "スーツ姿の男性が資料確認。投資・資産運用の信頼感を演出",
        "videoUrl": "/videos/hero-finance-man.mp4",
        "keywords": ["金融", "投資", "スーツ", "ビジネス", "信頼"],
        "suitable_for": ["投資", "FX", "資産運用", "金融教育"],
        "theme_match": ["urgent_red", "gold_premium"],
    },
    {
        "id": "top-hero-money-rain",
        "name": "ヒーロー（マネーシャワー）",
        "description": "舞い落ちる紙幣の映像。キャンペーンや成果訴求の高揚感",
        "videoUrl": "/videos/hero-money-rain.mov",
        "keywords": ["お金", "紙幣", "成果", "リッチ", "キャンペーン"],
        "suitable_for": ["投資", "FX", "副業", "ビジネス"],
        "theme_match": ["urgent_red", "gold_premium"],
    },
    {
        "id": "top-hero-keyboard",
        "name": "ヒーロー（キーボード操作）",
        "description": "メカニカルキーボード打鍵。SaaSや開発支援のプロフェッショナル感",
        "videoUrl": "/videos/hero-keyboard.mp4",
        "keywords": ["キーボード", "タイピング", "開発", "技術", "プログラミング"],
        "suitable_for": ["Web制作", "プログラミング", "SaaS", "ITスキル"],
        "theme_match": ["power_blue"],
    },
    {
        "id": "top-hero-keyboard-precision",
        "name": "ヒーロー（キーボード・精密作業）",
        "description": "高速タイピングする手元。クリエイティブや執筆サービスに最適",
        "videoUrl": "/videos/hero-keyboard-2.mp4",
        "keywords": ["キーボード", "タイピング", "執筆", "クリエイティブ"],
        "suitable_for": ["ライティング", "Webスキル", "執筆講座"],
        "theme_match": ["power_blue"],
    },
    {
        "id": "top-hero-puzzle",
        "name": "ヒーロー（ジグソーパズル）",
        "description": "パズルを組み合わせる映像。戦略立案やコンサルティングの「構造化」",
        "videoUrl": "/videos/hero-jigsaw-puzzle.mp4",
        "keywords": ["パズル", "戦略", "組み立て", "構造", "思考"],
        "suitable_for": ["コンサルティング", "戦略", "ビジネス"],
        "theme_match": ["gold_premium", "power_blue"],
    },
    {
        "id": "top-hero-clock",
        "name": "ヒーロー（回転する時計）",
        "description": "回転する壁時計。時間管理やデッドラインの緊張感を表現",
        "videoUrl": "/videos/hero-rotating-clock.mp4",
        "keywords": ["時計", "時間", "期限", "デッドライン", "管理"],
        "suitable_for": ["時間管理", "生産性", "習慣化"],
        "theme_match": ["urgent_red", "power_blue"],
    },
    {
        "id": "top-hero-leather-shoes",
        "name": "ヒーロー（革靴のビジネスパーソン）",
        "description": "颯爽と歩く革靴の映像。ビジネスエリート向けサービスの躍動感",
        "videoUrl": "/videos/hero-leather-shoes.mp4",
        "keywords": ["革靴", "ビジネス", "歩く", "エリート", "スーツ"],
        "suitable_for": ["ビジネス", "自己啓発", "キャリア"],
        "theme_match": ["gold_premium"],
    },
]

# 画像背景のヒーローブロック
HERO_IMAGE_TEMPLATES = [
    {
        "id": "top-hero-image-1",
        "name": "ヒーロー（イメージ）",
        "description": "動画を使わずに背景画像で魅せるフルスクリーンヒーロー",
        "templateId": "top-hero-image-1",
    }
]

# 新しいブロックタイプマッピング
NEW_BLOCK_TYPES = {
    # ヒーロー
    "hero": ["top-hero-1", "top-hero-image-1"],
    
    # コンテンツ
    "highlights": ["top-highlights-1"],
    "problem": ["top-problem-1"],
    "before-after": ["top-before-after-1"],
    "testimonials": ["top-testimonials-1"],
    "faq": ["top-faq-1"],
    "media-spotlight": ["top-media-spotlight-1"],
    
    # コンバージョン
    "cta": ["top-cta-1"],
    "inline-cta": ["top-inline-cta-1"],
    "pricing": ["top-pricing-1"],
    
    # 信頼・権威
    "bonus": ["top-bonus-1"],
    "guarantee": ["top-guarantee-1"],
    
    # 緊急性
    "countdown": ["top-countdown-1"],
}


def select_hero_for_business(business: str, target: str, goal: str, theme: str) -> str:
    """
    ビジネス情報から最適なヒーローブロックを選択
    
    Args:
        business: ジャンル（例：投資・FX・仮想通貨）
        target: ターゲット（例：20-30代男性）
        goal: 目標（例：高額商品購入）
        theme: テーマカラー（例：urgent_red）
    
    Returns:
        最適なヒーローブロックのID
    """
    business_lower = business.lower()
    
    # キーワードマッチング
    keyword_map = {
        "投資": ["hero-finance", "hero-money-rain", "hero-night-road"],
        "fx": ["hero-finance", "hero-money-rain", "hero-night-road"],
        "仮想通貨": ["hero-finance", "hero-gold-particles"],
        "ダイエット": ["hero-running-man", "hero-beach"],
        "筋トレ": ["hero-running-man"],
        "フィットネス": ["hero-running-man"],
        "英語": ["hero-book-flip", "hero-keyboard-precision"],
        "資格": ["hero-book-flip"],
        "学習": ["hero-book-flip"],
        "恋愛": ["hero-couple"],
        "モテ": ["hero-couple"],
        "副業": ["hero-night-crossing", "hero-downtown"],
        "ビジネス": ["hero-night-crossing", "hero-downtown", "hero-leather-shoes"],
        "sn": ["hero-smartphone"],  # SNS
        "集客": ["hero-downtown", "hero-smartphone"],
        "マーケティング": ["hero-downtown", "hero-night-crossing"],
        "転売": ["hero-smartphone", "hero-downtown"],
        "物販": ["hero-smartphone"],
        "ライティング": ["hero-keyboard", "hero-keyboard-precision"],
        "web": ["hero-keyboard"],
        "自己啓発": ["hero-tiger", "hero-smoke", "hero-beach"],
        "コーチング": ["hero-tiger", "hero-smoke"],
        "プログラミング": ["hero-keyboard"],
        "開発": ["hero-keyboard"],
    }
    
    # ビジネスキーワードからマッチング
    matched_heroes = []
    for keyword, heroes in keyword_map.items():
        if keyword in business_lower:
            matched_heroes.extend(heroes)
    
    # テーマとの親和性チェック
    theme_matched_heroes = []
    for hero in HERO_VIDEO_TEMPLATES:
        if theme in hero["theme_match"]:
            hero_id_short = hero["id"].replace("top-", "")
            if hero_id_short in matched_heroes:
                theme_matched_heroes.append(hero["id"])
    
    # マッチしたヒーローがあればそれを返す
    if theme_matched_heroes:
        return theme_matched_heroes[0]
    
    # マッチしたヒーローがあればそれを返す（テーマ無視）
    if matched_heroes:
        for hero in HERO_VIDEO_TEMPLATES:
            hero_id_short = hero["id"].replace("top-", "")
            if hero_id_short in matched_heroes:
                return hero["id"]
    
    # デフォルト：テーマに合うヒーローを返す
    for hero in HERO_VIDEO_TEMPLATES:
        if theme in hero["theme_match"]:
            return hero["id"]
    
    # 最終フォールバック
    return "top-hero-landing"


def get_hero_metadata(hero_id: str) -> Optional[Dict]:
    """ヒーローIDからメタデータを取得"""
    for hero in HERO_VIDEO_TEMPLATES:
        if hero["id"] == hero_id:
            return hero
    return None


def get_all_heroes_metadata() -> List[Dict]:
    """全ヒーローのメタデータを返す（AI選択用）"""
    return HERO_VIDEO_TEMPLATES
