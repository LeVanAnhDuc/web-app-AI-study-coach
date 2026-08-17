from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.modules.auth.models import User
from app.security import InvalidToken, decode_access_token

_scheme = HTTPBearer(auto_error=False)

_CHUA_DANG_NHAP = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Bạn cần đăng nhập để tiếp tục.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise _CHUA_DANG_NHAP
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise _CHUA_DANG_NHAP from None

    user = await session.get(User, user_id)
    if user is None:
        raise _CHUA_DANG_NHAP
    return user
