import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.auth.models import RefreshToken, User
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


class InvalidRefreshToken(Exception):
    """Refresh token không tồn tại, đã dùng, đã thu hồi, hoặc đã hết hạn."""


# Refresh token là 48 byte entropy ngẫu nhiên từ secrets.token_urlsafe, không phải mật
# khẩu do người dùng chọn, nên không có gì để dò ngược (brute-force); một hàm băm chậm
# như argon2 chỉ làm chậm mỗi lần refresh mà không tăng thêm an toàn nào, nên SHA-256 là
# lựa chọn đúng đắn ở đây — đừng "nâng cấp" nó lên argon2.
def _bam_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _tao_ban_ghi_token_moi(user: User) -> tuple[str, RefreshToken]:
    """Sinh chuỗi token thô và dựng bản ghi RefreshToken tương ứng, chưa thêm vào session
    và chưa commit — dùng chung cho cả cấp mới (login) lẫn xoay vòng (refresh) để hai nơi
    đó có thể tự quyết định ranh giới transaction/commit của riêng mình."""
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    record = RefreshToken(
        user_id=user.id,
        token_hash=_bam_token(raw),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
    )
    return raw, record


async def issue_refresh_token(session: AsyncSession, user: User) -> str:
    raw, record = _tao_ban_ghi_token_moi(user)
    session.add(record)
    await session.commit()
    return raw


async def rotate_refresh_token(session: AsyncSession, raw_token: str) -> tuple[User, str]:
    now = datetime.now(UTC)
    # Thu hồi bằng một UPDATE có điều kiện, nguyên tử ở tầng CSDL: nếu hai request đồng
    # thời cùng trình một refresh token, chỉ một request khớp điều kiện WHERE (token còn
    # tồn tại, chưa bị thu hồi, chưa hết hạn) và RETURNING trả về đúng một dòng cho nó;
    # request còn lại nhận 0 dòng vì CSDL đã cập nhật revoked_at trước đó. Kiểm tra
    # "đọc rồi ghi" ở tầng ứng dụng không thể ngăn race này — chỉ CSDL mới phân xử được.
    result = await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == _bam_token(raw_token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(RefreshToken.user_id)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        # Không tồn tại, đã bị thu hồi, đã hết hạn, hoặc vừa bị một request đồng thời
        # khác chiếm mất — bốn trường hợp này không thể phân biệt được với người gọi.
        raise InvalidRefreshToken()

    user = await session.get(User, user_id)
    if user is None:
        raise InvalidRefreshToken()

    # Thu hồi token cũ và cấp token mới trong cùng một transaction, commit đúng một lần:
    # nếu bước cấp mới thất bại, rollback sẽ hoàn tác luôn việc thu hồi, tránh tình huống
    # người dùng bị đăng xuất do lỗi tạm thời dù token cũ đáng lẽ vẫn còn hợp lệ.
    new_raw, new_record = _tao_ban_ghi_token_moi(user)
    session.add(new_record)
    await session.commit()
    return user, new_raw
