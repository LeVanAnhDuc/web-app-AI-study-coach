import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


class InvalidToken(Exception):
    """Token thiếu, sai chữ ký, sai định dạng, hoặc đã hết hạn."""


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError):
        return False


def create_access_token(user_id: uuid.UUID, now: datetime) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_access_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, now: datetime | None = None) -> uuid.UUID:
    settings = get_settings()
    moment = now or datetime.now(UTC)
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken("Token không hợp lệ") from exc

    if int(payload.get("exp", 0)) <= int(moment.timestamp()):
        raise InvalidToken("Token đã hết hạn")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidToken("Token thiếu định danh người dùng") from exc
