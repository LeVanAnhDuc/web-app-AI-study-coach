from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.modules.auth import service
from app.modules.auth.schemas import RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterIn,
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    try:
        user = await service.register_user(session, payload.email, payload.password)
    except service.EmailAlreadyUsed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email này đã được đăng ký.",
        ) from None
    return UserOut(id=user.id, email=user.email)
