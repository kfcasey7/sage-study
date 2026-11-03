from __future__ import annotations

from fastapi import APIRouter

from ..services import updates

router = APIRouter(prefix="/api/updates", tags=["updates"])


@router.get("")
async def check(force: bool = False) -> dict:
    return await updates.check(force=force)


@router.post("/apply")
async def apply() -> dict:
    return await updates.apply()
