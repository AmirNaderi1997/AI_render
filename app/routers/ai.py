"""AI provider diagnostics that never expose provider credentials."""
from fastapi import APIRouter

from brain.ai_provider import provider_status

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def ai_status() -> dict:
    return provider_status()
