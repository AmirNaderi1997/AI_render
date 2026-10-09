from fastapi import APIRouter, Depends, HTTPException

from hermes.schemas import BestTimesRequest, CaptionRequest, ContentPlanRequest, HashtagsRequest
from hermes.security import current_user, owned_account
from hermes.services.advisor_service import advise

router = APIRouter(prefix="/api/hermes/advisor", tags=["hermes-advisor"])


async def run(kind, body, user):
    await owned_account(body.account_id, user)
    try:
        return await advise(body.account_id, kind, body.model_dump())
    except Exception as exc:
        raise HTTPException(502, detail={"code": "ADVISOR_UNAVAILABLE"}) from exc


@router.post("/best-times")
async def best_times(body: BestTimesRequest, user=Depends(current_user)):
    return await run("best_time", body, user)


@router.post("/hashtags")
async def hashtags(body: HashtagsRequest, user=Depends(current_user)):
    return await run("hashtags", body, user)


@router.post("/caption")
async def caption(body: CaptionRequest, user=Depends(current_user)):
    return await run("caption", body, user)


@router.post("/content-plan")
async def content_plan(body: ContentPlanRequest, user=Depends(current_user)):
    return await run("content_plan", body, user)
