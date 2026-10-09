from fastapi import APIRouter, Depends, HTTPException

from hermes.security import current_user, owned_account
from hermes.services.analytics_service import account_insights, post_insights
from hermes.services.instagram_api import InstagramError

router = APIRouter(prefix="/api/hermes/analytics", tags=["hermes-analytics"])


def error(exc):
    raise HTTPException(exc.status, detail={"code": exc.code}) from exc


@router.get("/account/{account_id}")
async def account(account_id: str, user=Depends(current_user)):
    row = await owned_account(account_id, user)
    try:
        return await account_insights(row)
    except InstagramError as exc:
        error(exc)


@router.get("/posts/{account_id}")
async def posts(account_id: str, user=Depends(current_user)):
    row = await owned_account(account_id, user)
    try:
        return await post_insights(row)
    except InstagramError as exc:
        error(exc)


@router.post("/refresh/{account_id}")
async def refresh(account_id: str, user=Depends(current_user)):
    row = await owned_account(account_id, user)
    try:
        return {"account": await account_insights(row, force=True), "posts": await post_insights(row, force=True)}
    except InstagramError as exc:
        error(exc)
