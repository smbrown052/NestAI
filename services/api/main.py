"""
services/api/main.py — NestAI FastAPI application entry point.

Start locally:
    uvicorn main:app --reload

API documentation:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)

Admin dashboard:
    http://localhost:8000/admin/    (requires JWT from POST /auth/login)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.users.router import router as users_router

app = FastAPI(
    title="NestAI API",
    description="Backend for the NestAI apartment comparison platform.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8501"],  # Next.js and Streamlit
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)


@app.get("/health")
def health_check():
    """Basic liveness probe."""
    return {"status": "ok"}
