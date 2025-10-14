# スワイプ型LP制作プラットフォーム ステップバイステップ実装計画書

## 目次
1. [Week 1-2: 基盤構築](#week-1-2-基盤構築)
2. [Week 3: コア機能実装](#week-3-コア機能実装)
3. [Week 4: 公開・分析機能](#week-4-公開分析機能)
4. [Week 5: ポイントシステム](#week-5-ポイントシステム)
5. [Week 6: 必須アクション機能](#week-6-必須アクション機能)
6. [Week 7: 改善機能](#week-7-改善機能)
7. [Week 8: テスト・リリース](#week-8-テストリリース)

---

## Week 1-2: 基盤構築

### Day 1-2: プロジェクトセットアップ

#### フロントエンド
```bash
# プロジェクト作成
npx create-next-app@latest swipelaunch-frontend --typescript --tailwind --app

# 依存関係インストール
cd swipelaunch-frontend
npm install @supabase/supabase-js @supabase/auth-helpers-nextjs
npm install zustand
npm install swiper framer-motion
npm install react-hook-form zod
npm install lucide-react clsx tailwind-merge
npm install @dnd-kit/core @dnd-kit/sortable # ドラッグ&ドロップ用
npm install recharts # グラフ表示用
npm install qrcode.react # QRコード生成
```

**ディレクトリ構成**
```
swipelaunch-frontend/
├── src/
│   ├── app/
│   │   ├── (auth)/
│   │   │   ├── login/
│   │   │   └── register/
│   │   ├── (dashboard)/
│   │   │   ├── dashboard/
│   │   │   ├── lp/
│   │   │   │   ├── create/
│   │   │   │   ├── [id]/edit/
│   │   │   │   └── [id]/analytics/
│   │   │   ├── products/
│   │   │   └── settings/
│   │   ├── [seller]/[slug]/ # LP公開ページ
│   │   └── product/[id]/ # 商材購入ページ
│   ├── components/
│   │   ├── ui/ # 共通UIコンポーネント
│   │   ├── lp-editor/ # LPエディタ関連
│   │   └── swipe-viewer/ # スワイプLP表示
│   ├── lib/
│   │   ├── supabase/ # Supabase設定
│   │   ├── api/ # API呼び出し
│   │   └── utils/ # ユーティリティ
│   ├── store/ # Zustand ストア
│   └── types/ # TypeScript型定義
├── public/
└── package.json
```

#### バックエンド
```bash
# プロジェクト作成
mkdir swipelaunch-backend
cd swipelaunch-backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存関係インストール
pip install fastapi==0.116.1
pip install uvicorn==0.35.0
pip install supabase>=2.4.0
pip install python-multipart==0.0.20
pip install pydantic==2.11.7
pip install python-dotenv>=0.19.0
pip install pillow>=10.0.0 # 画像処理
pip install boto3>=1.28.0 # Cloudflare R2用
pip install redis>=4.0.0
pip install httpx>=0.24.0

# requirements.txt生成
pip freeze > requirements.txt
```

**ディレクトリ構成**
```
swipelaunch-backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── user.py
│   │   ├── landing_page.py
│   │   ├── product.py
│   │   └── analytics.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── lp.py
│   │   ├── products.py
│   │   ├── analytics.py
│   │   └── media.py
│   ├── services/
│   │   ├── storage.py # Cloudflare R2
│   │   ├── image_processor.py
│   │   └── analytics_engine.py
│   ├── middleware/
│   │   └── auth.py
│   └── utils/
│       └── helpers.py
├── tests/
├── .env
├── requirements.txt
└── README.md
```

---

### Day 3-4: データベース設計とテーブル作成

#### Supabase設定
1. Supabaseプロジェクト作成: https://supabase.com/dashboard
2. `.env.local` 設定

**フロントエンド `.env.local`**
```env
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

**バックエンド `.env`**
```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_service_role_key
CLOUDFLARE_R2_ACCOUNT_ID=your_account_id
CLOUDFLARE_R2_ACCESS_KEY=your_access_key
CLOUDFLARE_R2_SECRET_KEY=your_secret_key
CLOUDFLARE_R2_BUCKET_NAME=swipelaunch-media
REDIS_URL=your_upstash_redis_url
```

#### テーブル作成SQL
```sql
-- users テーブル（Supabase Authと連携）
CREATE TABLE users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email VARCHAR(255) UNIQUE NOT NULL,
  username VARCHAR(100) UNIQUE NOT NULL,
  user_type VARCHAR(20) NOT NULL CHECK (user_type IN ('seller', 'buyer')),
  point_balance INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- landing_pages テーブル
CREATE TABLE landing_pages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  seller_id UUID REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  slug VARCHAR(100) UNIQUE NOT NULL,
  status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  swipe_direction VARCHAR(20) DEFAULT 'vertical' CHECK (swipe_direction IN ('vertical', 'horizontal')),
  is_fullscreen BOOLEAN DEFAULT false,
  total_views INTEGER DEFAULT 0,
  total_cta_clicks INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- lp_steps テーブル
CREATE TABLE lp_steps (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL,
  image_url TEXT NOT NULL,
  video_url TEXT,
  animation_type VARCHAR(50),
  step_views INTEGER DEFAULT 0,
  step_exits INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(lp_id, step_order)
);

-- lp_ctas テーブル
CREATE TABLE lp_ctas (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_id UUID REFERENCES lp_steps(id) ON DELETE SET NULL,
  cta_type VARCHAR(50) NOT NULL,
  button_image_url TEXT NOT NULL,
  button_position VARCHAR(20) DEFAULT 'bottom',
  link_url TEXT,
  is_required BOOLEAN DEFAULT false,
  click_count INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

-- products テーブル
CREATE TABLE products (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  seller_id UUID REFERENCES users(id) ON DELETE CASCADE,
  lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  price_in_points INTEGER NOT NULL,
  stock_quantity INTEGER,
  is_available BOOLEAN DEFAULT true,
  total_sales INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- point_transactions テーブル
CREATE TABLE point_transactions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  transaction_type VARCHAR(50) NOT NULL,
  amount INTEGER NOT NULL,
  related_product_id UUID REFERENCES products(id),
  description TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- lp_analytics テーブル
CREATE TABLE lp_analytics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  total_sessions INTEGER DEFAULT 0,
  unique_visitors INTEGER DEFAULT 0,
  avg_time_on_page FLOAT,
  conversion_rate FLOAT,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(lp_id, date)
);

-- ab_tests テーブル
CREATE TABLE ab_tests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  test_name VARCHAR(255) NOT NULL,
  variant_a_id UUID REFERENCES lp_steps(id),
  variant_b_id UUID REFERENCES lp_steps(id),
  status VARCHAR(20) DEFAULT 'running',
  traffic_split INTEGER DEFAULT 50,
  winner VARCHAR(10),
  created_at TIMESTAMP DEFAULT NOW(),
  ended_at TIMESTAMP
);

-- インデックス作成
CREATE INDEX idx_landing_pages_seller ON landing_pages(seller_id);
CREATE INDEX idx_landing_pages_slug ON landing_pages(slug);
CREATE INDEX idx_lp_steps_lp_id ON lp_steps(lp_id);
CREATE INDEX idx_products_seller ON products(seller_id);
CREATE INDEX idx_point_transactions_user ON point_transactions(user_id);
CREATE INDEX idx_lp_analytics_lp_date ON lp_analytics(lp_id, date);
```

---

### Day 5-7: 認証システム実装

#### 1. Supabase Auth設定（フロントエンド）

**`src/lib/supabase/client.ts`**
```typescript
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs'

export const supabase = createClientComponentClient()
```

**`src/lib/supabase/server.ts`**
```typescript
import { createServerComponentClient } from '@supabase/auth-helpers-nextjs'
import { cookies } from 'next/headers'

export const createServerSupabaseClient = () => {
  return createServerComponentClient({ cookies })
}
```

#### 2. 認証API（バックエンド）

**`app/routes/auth.py`**
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from supabase import create_client

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: str
    user_type: str  # 'seller' or 'buyer'

@router.post("/register")
async def register(data: RegisterRequest):
    # Supabase Auth でユーザー作成
    # users テーブルに追加情報を挿入
    pass

@router.post("/login")
async def login(email: EmailStr, password: str):
    # Supabase Auth でログイン
    pass
```

#### 3. 認証ページ（フロントエンド）

**`src/app/(auth)/register/page.tsx`**
```typescript
'use client'
import { useState } from 'react'
import { supabase } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [username, setUsername] = useState('')
  const [userType, setUserType] = useState<'seller' | 'buyer'>('seller')
  const router = useRouter()

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          username,
          user_type: userType
        }
      }
    })

    if (error) {
      console.error('Registration error:', error)
      return
    }

    // users テーブルに追加情報を挿入
    await supabase.from('users').insert({
      id: data.user?.id,
      email,
      username,
      user_type: userType
    })

    router.push('/dashboard')
  }

  return (
    // 登録フォームUI
  )
}
```

---

### Day 8-10: 基本UI/UXデザイン

#### 1. 共通UIコンポーネント作成

**`src/components/ui/button.tsx`**
```typescript
import { forwardRef } from 'react'
import { cn } from '@/lib/utils'

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost'
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', ...props }, ref) => {
    return (
      <button
        className={cn(
          'px-4 py-2 rounded-lg font-medium transition-colors',
          variant === 'default' && 'bg-blue-600 text-white hover:bg-blue-700',
          variant === 'outline' && 'border border-gray-300 hover:bg-gray-100',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)

Button.displayName = 'Button'

export { Button }
```

#### 2. ダッシュボードレイアウト

**`src/app/(dashboard)/layout.tsx`**
```typescript
import { Sidebar } from '@/components/dashboard/sidebar'
import { Header } from '@/components/dashboard/header'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
```

---

## Week 3: コア機能実装

### Day 11-13: LP作成エディタ

#### 1. LP作成ページ

**`src/app/(dashboard)/lp/create/page.tsx`**
```typescript
'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { StepEditor } from '@/components/lp-editor/step-editor'
import { CTAEditor } from '@/components/lp-editor/cta-editor'

export default function CreateLPPage() {
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [swipeDirection, setSwipeDirection] = useState<'vertical' | 'horizontal'>('vertical')
  const [steps, setSteps] = useState<any[]>([])
  const [ctas, setCtas] = useState<any[]>([])
  const router = useRouter()

  const handleSave = async () => {
    // LP保存API呼び出し
  }

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">LP作成</h1>
      
      {/* 基本設定 */}
      <div className="bg-white p-6 rounded-lg shadow mb-6">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="LP名"
          className="w-full mb-4 px-4 py-2 border rounded"
        />
        <input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="スラッグ（URL用）"
          className="w-full mb-4 px-4 py-2 border rounded"
        />
        <select
          value={swipeDirection}
          onChange={(e) => setSwipeDirection(e.target.value as any)}
          className="w-full px-4 py-2 border rounded"
        >
          <option value="vertical">縦スワイプ</option>
          <option value="horizontal">横スワイプ</option>
        </select>
      </div>

      {/* ステップエディタ */}
      <StepEditor steps={steps} setSteps={setSteps} />

      {/* CTAエディタ */}
      <CTAEditor ctas={ctas} setCtas={setCtas} />

      <div className="flex gap-4 mt-6">
        <button onClick={handleSave} className="btn-primary">
          下書き保存
        </button>
        <button className="btn-secondary">プレビュー</button>
      </div>
    </div>
  )
}
```

#### 2. ステップエディタコンポーネント

**`src/components/lp-editor/step-editor.tsx`**
```typescript
'use client'
import { useState } from 'react'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { StepItem } from './step-item'

export function StepEditor({ steps, setSteps }: any) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const handleDragEnd = (event: any) => {
    const { active, over } = event
    if (active.id !== over.id) {
      setSteps((items: any[]) => {
        const oldIndex = items.findIndex((i) => i.id === active.id)
        const newIndex = items.findIndex((i) => i.id === over.id)
        return arrayMove(items, oldIndex, newIndex)
      })
    }
  }

  const handleAddStep = () => {
    setSteps([...steps, { id: Date.now(), image_url: '', order: steps.length }])
  }

  return (
    <div className="bg-white p-6 rounded-lg shadow mb-6">
      <h2 className="text-xl font-bold mb-4">ステップ編集</h2>
      
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={steps.map((s: any) => s.id)}
          strategy={verticalListSortingStrategy}
        >
          {steps.map((step: any, index: number) => (
            <StepItem key={step.id} step={step} index={index} />
          ))}
        </SortableContext>
      </DndContext>

      <button onClick={handleAddStep} className="mt-4 btn-outline">
        + ステップ追加
      </button>
    </div>
  )
}
```

---

### Day 14-15: 画像アップロード機能

#### 1. Cloudflare R2設定

**バックエンド `app/services/storage.py`**
```python
import boto3
from botocore.config import Config
from app.config import settings

class CloudflareR2Storage:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            endpoint_url=f'https://{settings.CLOUDFLARE_R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            aws_access_key_id=settings.CLOUDFLARE_R2_ACCESS_KEY,
            aws_secret_access_key=settings.CLOUDFLARE_R2_SECRET_KEY,
            config=Config(signature_version='s3v4')
        )
        self.bucket_name = settings.CLOUDFLARE_R2_BUCKET_NAME

    def upload_file(self, file_content: bytes, file_name: str, content_type: str):
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=file_name,
            Body=file_content,
            ContentType=content_type
        )
        return f'https://pub-{self.account_id}.r2.dev/{file_name}'

    def delete_file(self, file_name: str):
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_name)

storage = CloudflareR2Storage()
```

#### 2. 画像アップロードAPI

**`app/routes/media.py`**
```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.storage import storage
from app.services.image_processor import optimize_image
import uuid

router = APIRouter(prefix="/media", tags=["media"])

@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type.startswith('image/'):
        raise HTTPException(400, "画像ファイルのみアップロード可能です")
    
    content = await file.read()
    
    # 画像最適化
    optimized_content = optimize_image(content)
    
    # ファイル名生成
    file_extension = file.filename.split('.')[-1]
    file_name = f"{uuid.uuid4()}.{file_extension}"
    
    # Cloudflare R2にアップロード
    url = storage.upload_file(optimized_content, file_name, file.content_type)
    
    return {"url": url}
```

#### 3. フロントエンド画像アップロード

**`src/components/lp-editor/image-upload.tsx`**
```typescript
'use client'
import { useState } from 'react'
import { Upload } from 'lucide-react'

export function ImageUpload({ onUpload }: { onUpload: (url: string) => void }) {
  const [uploading, setUploading] = useState(false)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/media/upload', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      onUpload(data.url)
    } catch (error) {
      console.error('Upload error:', error)
    } finally {
      setUploading(false)
    }
  }

  return (
    <label className="border-2 border-dashed border-gray-300 rounded-lg p-8 cursor-pointer hover:border-blue-500">
      <div className="flex flex-col items-center">
        <Upload className="w-12 h-12 text-gray-400 mb-2" />
        <span className="text-gray-600">
          {uploading ? 'アップロード中...' : '画像を選択'}
        </span>
      </div>
      <input
        type="file"
        accept="image/*"
        onChange={handleFileChange}
        className="hidden"
      />
    </label>
  )
}
```

---

### Day 16-17: ステップ並び替え・プレビュー機能

実装内容は上記のステップエディタと、以下のプレビュー機能を含む。

**`src/app/(dashboard)/lp/[id]/preview/page.tsx`**
```typescript
'use client'
import { SwipeLPViewer } from '@/components/swipe-viewer/swipe-lp-viewer'
import QRCode from 'qrcode.react'

export default function PreviewPage({ params }: { params: { id: string } }) {
  const previewUrl = `${window.location.origin}/preview/${params.id}`

  return (
    <div className="flex gap-8">
      {/* スマホプレビュー */}
      <div className="flex-1">
        <div className="max-w-[375px] mx-auto border-8 border-gray-800 rounded-3xl overflow-hidden">
          <SwipeLPViewer lpId={params.id} />
        </div>
      </div>

      {/* QRコード */}
      <div className="w-64">
        <h3 className="text-lg font-bold mb-4">実機プレビュー</h3>
        <QRCode value={previewUrl} size={200} />
        <p className="mt-4 text-sm text-gray-600">
          QRコードをスキャンして実機で確認
        </p>
      </div>
    </div>
  )
}
```

---

## Week 4: 公開・分析機能

### Day 18-20: スワイプLP表示

#### 1. スワイプビューアーコンポーネント

**`src/components/swipe-viewer/swipe-lp-viewer.tsx`**
```typescript
'use client'
import { useState, useEffect } from 'react'
import { Swiper, SwiperSlide } from 'swiper/react'
import { EffectCreative, Pagination } from 'swiper/modules'
import 'swiper/css'
import 'swiper/css/effect-creative'
import 'swiper/css/pagination'

export function SwipeLPViewer({ lpId }: { lpId: string }) {
  const [lpData, setLpData] = useState<any>(null)

  useEffect(() => {
    // LP データ取得
    fetch(`/api/lp/${lpId}`)
      .then((res) => res.json())
      .then((data) => setLpData(data))
  }, [lpId])

  if (!lpData) return <div>Loading...</div>

  return (
    <div className="h-screen relative">
      <Swiper
        direction={lpData.swipe_direction === 'vertical' ? 'vertical' : 'horizontal'}
        effect="creative"
        creativeEffect={{
          prev: {
            translate: [0, '-100%', 0],
          },
          next: {
            translate: [0, '100%', 0],
          },
        }}
        pagination={{ clickable: true }}
        modules={[EffectCreative, Pagination]}
        className="h-full"
      >
        {lpData.steps.map((step: any, index: number) => (
          <SwiperSlide key={step.id}>
            <img
              src={step.image_url}
              alt={`Step ${index + 1}`}
              className="w-full h-full object-cover"
            />
          </SwiperSlide>
        ))}
      </Swiper>

      {/* CTA ボタン */}
      {lpData.ctas.map((cta: any) => (
        <button
          key={cta.id}
          className={`fixed ${cta.button_position === 'bottom' ? 'bottom-4' : 'top-4'} left-1/2 -translate-x-1/2 z-50`}
          onClick={() => handleCTAClick(cta)}
        >
          <img src={cta.button_image_url} alt="CTA" className="max-w-xs" />
        </button>
      ))}
    </div>
  )
}
```

---

### Day 21-23: 専用URL発行・分析機能

#### 1. LP公開ページ

**`src/app/[seller]/[slug]/page.tsx`**
```typescript
import { createServerSupabaseClient } from '@/lib/supabase/server'
import { SwipeLPViewer } from '@/components/swipe-viewer/swipe-lp-viewer'
import { notFound } from 'next/navigation'

export default async function PublicLPPage({
  params,
}: {
  params: { seller: string; slug: string }
}) {
  const supabase = createServerSupabaseClient()

  // LP データ取得
  const { data: lp } = await supabase
    .from('landing_pages')
    .select(`
      *,
      steps:lp_steps(*),
      ctas:lp_ctas(*)
    `)
    .eq('slug', params.slug)
    .single()

  if (!lp) notFound()

  // PV カウント
  await supabase
    .from('landing_pages')
    .update({ total_views: lp.total_views + 1 })
    .eq('id', lp.id)

  return <SwipeLPViewer lpData={lp} />
}
```

#### 2. 分析ダッシュボード

**`src/app/(dashboard)/lp/[id]/analytics/page.tsx`**
```typescript
'use client'
import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'

export default function AnalyticsPage({ params }: { params: { id: string } }) {
  const [analytics, setAnalytics] = useState<any>(null)

  useEffect(() => {
    fetch(`/api/analytics/${params.id}`)
      .then((res) => res.json())
      .then((data) => setAnalytics(data))
  }, [params.id])

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">LP分析</h1>

      {/* KPI カード */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-gray-600 mb-2">総閲覧数</h3>
          <p className="text-3xl font-bold">{analytics?.total_views}</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-gray-600 mb-2">CTAクリック数</h3>
          <p className="text-3xl font-bold">{analytics?.total_cta_clicks}</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-gray-600 mb-2">CVR</h3>
          <p className="text-3xl font-bold">{analytics?.conversion_rate}%</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-gray-600 mb-2">平均滞在時間</h3>
          <p className="text-3xl font-bold">{analytics?.avg_time_on_page}s</p>
        </div>
      </div>

      {/* ステップファネル */}
      <div className="bg-white p-6 rounded-lg shadow mb-8">
        <h2 className="text-xl font-bold mb-4">ステップファネル</h2>
        {/* ファネルチャート実装 */}
      </div>

      {/* 時系列グラフ */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-bold mb-4">日別PV推移</h2>
        <LineChart width={800} height={300} data={analytics?.daily_data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="views" stroke="#3b82f6" />
        </LineChart>
      </div>
    </div>
  )
}
```

---

## Week 5-8: フェーズ2 機能実装

*(Week 5-8の詳細は省略しますが、以下の機能を順次実装)*

### Week 5: ポイントシステム
- ポイント購入API
- 商材登録・管理画面
- 購入フロー実装

### Week 6: 必須アクション機能
- メルマガ登録ゲート（SendGrid連携）
- LINE連携ゲート（LINE Messaging API）
- 進行制御ロジック

### Week 7: 改善機能
- バージョン管理システム
- ABテスト機能
- 動画アップロード対応

### Week 8: テスト・リリース
- E2Eテスト（Playwright）
- パフォーマンス最適化
- 本番デプロイ

---

## 開発時の注意事項

1. **Git管理**: 各機能実装ごとにコミット
2. **テスト**: 重要機能には単体テスト必須
3. **環境変数**: `.env` をGit追跡しない
4. **コードレビュー**: Droidと確認しながら進める
5. **ドキュメント**: 実装した機能はREADMEに追記

---

## 次のステップ

この計画書を基に開発を開始しますか？
具体的な実装を進める前に、開発環境セットアップガイドとAPI仕様書を確認してください。
