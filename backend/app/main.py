from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from app.config import settings

security = HTTPBearer()

app = FastAPI(
    title="Ｄ－swipe API",
    version="1.0.0",
    description="スワイプ型LP制作プラットフォームAPI",
    swagger_ui_parameters={"persistAuthorization": True}
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "message": "Ｄ－swipe API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "environment": "development"
    }

# ルート追加
from app.routes import (
    admin,
    ai,
    analytics,
    announcements,
    auth,
    line,
    lp,
    media,
    notes,
    points,
    products,
    public,
    salon_announcements,
    salon_assets,
    salon_roles,
    salon_events,
    salon_posts,
    subscriptions,
    salons,
    test,
    webhooks,
    x_auth,
)
app.include_router(test.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(x_auth.router, prefix="/api")
app.include_router(lp.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(points.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(line.router, prefix="/api")
app.include_router(announcements.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(salons.router, prefix="/api")
app.include_router(salon_announcements.router, prefix="/api")
app.include_router(salon_assets.router, prefix="/api")
app.include_router(salon_roles.router, prefix="/api")
app.include_router(salon_events.router, prefix="/api")
app.include_router(salon_posts.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
