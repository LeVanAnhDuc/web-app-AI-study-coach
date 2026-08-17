from sqlalchemy import select
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
    await session.commit()
    await session.refresh(user)
    return user
