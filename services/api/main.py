"""
services/api/main.py — NestAI FastAPI application entry point.

Start locally:
    uvicorn main:app --reload

API documentation:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)

Admin dashboard:
    http://localhost:8000/admin/    (JSON API, use Swagger UI or a REST client)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router

app = FastAPI(
    title="NestAI API",
    description="Backend for the NestAI apartment comparison platform.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(admin_router)


@app.get("/health")
def health_check():
    """Basic liveness probe."""
    return {"status": "ok"}
