from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.security import hash_password, verify_password

# Hash giả dùng để verify_password luôn chạy dù email có tồn tại hay không,
# tránh lộ thông tin qua thời gian phản hồi (email không tồn tại sẽ trả lời
# nhanh hơn hẳn nếu bỏ qua bước băm). Tính một lần khi import module.
_MAT_KHAU_GIA_DE_CHONG_DO_THOI_GIAN = hash_password("mat-khau-gia-khong-dung-that")


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


class InvalidCredentials(Exception):
    """Email không tồn tại hoặc mật khẩu sai. Cố ý không phân biệt hai trường hợp."""


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    normalized = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == normalized))
    # Luôn băm-so-sánh đúng một lần dù user có tồn tại hay không: nếu để short-circuit
    # (vd. "user is None or not verify_password(...)") thì trường hợp email không tồn
    # tại sẽ trả lời nhanh hơn hẳn trường hợp sai mật khẩu, lộ ra qua thời gian phản hồi
    # rằng email đó đã được đăng ký hay chưa — dù thông báo lỗi giống hệt nhau.
    mat_khau_hop_le = verify_password(
        password,
        user.password_hash if user is not None else _MAT_KHAU_GIA_DE_CHONG_DO_THOI_GIAN,
    )
    if user is None or not mat_khau_hop_le:
        raise InvalidCredentials(normalized)
    return user
