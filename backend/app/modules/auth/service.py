from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.security import hash_password


class EmailAlreadyUsed(Exception):
    """Email đã tồn tại trong hệ thống."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register_user(session: AsyncSession, email: str, password: str) -> User:
    normalized = normalize_email(email)
    existing = await session.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise EmailAlreadyUsed(normalized)

    user = User(email=normalized, password_hash=hash_password(password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Hai request đăng ký cùng email gần như đồng thời đều có thể vượt qua kiểm tra
        # SELECT ở trên trước khi request kia commit; ràng buộc unique trên cột email sẽ
        # chặn INSERT thứ hai. Phải rollback trước khi raise vì session đã ở trạng thái
        # lỗi sau một commit thất bại, nếu không thao tác kế tiếp trên session sẽ báo lỗi
        # không liên quan, gây khó hiểu.
        await session.rollback()
        raise EmailAlreadyUsed(normalized) from None
    await session.refresh(user)
    return user
