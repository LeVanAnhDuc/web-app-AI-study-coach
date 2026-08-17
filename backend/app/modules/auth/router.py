from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.modules.auth import service
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import LoginIn, RefreshIn, RegisterIn, TokenPair, UserOut
from app.security import create_access_token

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


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginIn,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    try:
        user = await service.authenticate(session, payload.email, payload.password)
    except service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng.",
        ) from None

    refresh_raw = await service.issue_refresh_token(session, user)
    settings = get_settings()
    return TokenPair(
        access_token=create_access_token(user.id, datetime.now(UTC)),
        refresh_token=refresh_raw,
        expires_in=settings.jwt_access_ttl_seconds,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshIn,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    try:
        user, new_refresh = await service.rotate_refresh_token(session, payload.refresh_token)
    except service.InvalidRefreshToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hiệu lực. Đăng nhập lại nhé.",
        ) from None

    settings = get_settings()
    return TokenPair(
        access_token=create_access_token(user.id, datetime.now(UTC)),
        refresh_token=new_refresh,
        expires_in=settings.jwt_access_ttl_seconds,
    )


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=current.id, email=current.email)
