from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.modules.auth.models import User
from app.security import InvalidToken, decode_access_token

_scheme = HTTPBearer(auto_error=False)


# Phải trả về một instance HTTPException MỚI mỗi lần gọi: raise đi raise lại cùng một
# instance khiến CPython gắn thêm frame mới vào chuỗi __traceback__ có sẵn của nó thay
# vì thay thế, và vì instance này ở cấp module nên không bao giờ bị garbage collect —
# chuỗi traceback (giữ tham chiếu tới session, credentials của từng request) cứ dài
# thêm mãi suốt vòng đời tiến trình. Đừng "tối ưu" nó thành hằng số cấp module.
def _chua_dang_nhap() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Bạn cần đăng nhập để tiếp tục.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise _chua_dang_nhap()
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise _chua_dang_nhap() from None

    user = await session.get(User, user_id)
    if user is None:
        raise _chua_dang_nhap()
    return user
