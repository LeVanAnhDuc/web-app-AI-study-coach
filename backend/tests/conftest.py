import os
from collections.abc import Mapping
from urllib.parse import urlsplit

_DATABASE_URL_TEST_MAC_DINH = "postgresql+asyncpg://coach:coach@localhost:15432/coach_test"


def lay_database_url_test(moi_truong: Mapping[str, str] | None = None) -> str:
    """Đọc TEST_DATABASE_URL từ môi trường (mặc định os.environ), có giá trị mặc định an toàn."""
    moi_truong = os.environ if moi_truong is None else moi_truong
    return moi_truong.get("TEST_DATABASE_URL", _DATABASE_URL_TEST_MAC_DINH)


def kiem_tra_ten_csdl_la_test(database_url: str) -> None:
    """Chặn test chạy trên CSDL không phải CSDL test.

    Hàm này chỉ phân tích chuỗi kết nối, không mở kết nối tới CSDL, để có thể
    kiểm thử độc lập mà không đụng tới bất kỳ CSDL thật nào.
    """
    ten_csdl = urlsplit(database_url).path.lstrip("/")
    assert ten_csdl.endswith("_test"), (
        f"Từ chối chạy test trên CSDL '{ten_csdl}': tên CSDL dùng cho test phải kết thúc "
        "bằng '_test' để tránh xóa nhầm dữ liệu phát triển."
    )


# Không dùng setdefault: DATABASE_URL luôn được gán từ TEST_DATABASE_URL (hoặc giá trị
# mặc định) để test không bao giờ vô tình chạy (và drop_all) trên CSDL phát triển mà
# một lập trình viên có thể đã export sẵn trong shell của họ.
_database_url_test = lay_database_url_test()
kiem_tra_ten_csdl_la_test(_database_url_test)
os.environ["DATABASE_URL"] = _database_url_test
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "bi-mat-chi-dung-trong-test")

from collections.abc import AsyncIterator  # noqa: E402

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db import Base, engine, session_factory  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def tao_bang() -> AsyncIterator[None]:
    # Kiểm tra lại ngay trước khi drop_all: đây là hành động phá hủy dữ liệu duy nhất
    # trong fixture, nên assert này không được phép bị bỏ qua trong bất kỳ trường hợp nào.
    kiem_tra_ten_csdl_la_test(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
