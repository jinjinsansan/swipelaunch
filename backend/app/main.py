from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from app.config import settings

security = HTTPBearer()

app = FastAPI(
    title="SwipeLaunch API",
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
        "message": "SwipeLaunch API is running",
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
from app.routes import test, auth, lp, media, public, analytics, products, points, ai
app.include_router(test.router)
app.include_router(auth.router)
app.include_router(lp.router)
app.include_router(media.router)
app.include_router(public.router)
app.include_router(analytics.router)
app.include_router(products.router)
app.include_router(points.router)
app.include_router(ai.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
