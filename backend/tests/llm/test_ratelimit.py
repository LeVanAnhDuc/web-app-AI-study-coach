import fakeredis.aioredis
import pytest
import redis.exceptions as redis_exceptions

from app.modules.llm.ratelimit import RateLimiterUnavailable, TokenBucket, bucket_for_provider
from app.modules.llm.types import LLMError, ProviderUnavailable, QuotaExhausted, RateLimited


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_lay_duoc_token_khi_thung_con_day(redis):
    bucket = TokenBucket(redis, key="t1", capacity=3, refill_per_second=0.0)
    assert await bucket.try_acquire(now=0.0) is True
    assert await bucket.try_acquire(now=0.0) is True
    assert await bucket.try_acquire(now=0.0) is True


@pytest.mark.asyncio
async def test_het_token_thi_bi_tu_choi(redis):
    bucket = TokenBucket(redis, key="t2", capacity=2, refill_per_second=0.0)
    await bucket.try_acquire(now=0.0)
    await bucket.try_acquire(now=0.0)
    assert await bucket.try_acquire(now=0.0) is False


@pytest.mark.asyncio
async def test_token_hoi_lai_theo_thoi_gian(redis):
    bucket = TokenBucket(redis, key="t3", capacity=2, refill_per_second=1.0)
    await bucket.try_acquire(now=0.0)
    await bucket.try_acquire(now=0.0)
    assert await bucket.try_acquire(now=0.0) is False
    assert await bucket.try_acquire(now=1.0) is True


@pytest.mark.asyncio
async def test_khong_hoi_qua_suc_chua(redis):
    bucket = TokenBucket(redis, key="t4", capacity=2, refill_per_second=1.0)
    await bucket.try_acquire(now=0.0)
    await bucket.try_acquire(now=0.0)
    assert await bucket.try_acquire(now=1000.0) is True
    assert await bucket.try_acquire(now=1000.0) is True
    assert await bucket.try_acquire(now=1000.0) is False


@pytest.mark.asyncio
async def test_hai_thung_khac_khoa_thi_doc_lap(redis):
    a = TokenBucket(redis, key="a", capacity=1, refill_per_second=0.0)
    b = TokenBucket(redis, key="b", capacity=1, refill_per_second=0.0)
    assert await a.try_acquire(now=0.0) is True
    assert await a.try_acquire(now=0.0) is False
    assert await b.try_acquire(now=0.0) is True


@pytest.mark.asyncio
async def test_tao_thung_tu_so_request_moi_phut(redis):
    bucket = bucket_for_provider(redis, "gemini", rpm=60)
    assert bucket.capacity == 60
    assert bucket.refill_per_second == pytest.approx(1.0)


# --- Ruling 4: namespacing theo provider và theo owner (shared / BYOK) ---


@pytest.mark.asyncio
async def test_hai_provider_khac_nhau_co_thung_doc_lap(redis):
    gemini = bucket_for_provider(redis, "gemini", rpm=1)
    groq = bucket_for_provider(redis, "groq", rpm=1)
    assert await gemini.try_acquire(now=0.0) is True
    assert await gemini.try_acquire(now=0.0) is False
    # groq chưa bị đụng tới, phải còn nguyên sức chứa dù cùng owner mặc định.
    assert await groq.try_acquire(now=0.0) is True


@pytest.mark.asyncio
async def test_shared_va_byok_cung_provider_co_thung_doc_lap(redis):
    dung_chung = bucket_for_provider(redis, "gemini", rpm=1)
    # owner ở đây mô phỏng một định danh mờ (băm khoá) — KHÔNG phải khoá API gốc.
    rieng_cua_mot_nguoi = bucket_for_provider(redis, "gemini", rpm=1, owner="byok:ab12cd34")
    assert await dung_chung.try_acquire(now=0.0) is True
    assert await dung_chung.try_acquire(now=0.0) is False
    # Hạn mức dùng chung đã cạn không được chặn nhầm người dùng khoá riêng.
    assert await rieng_cua_mot_nguoi.try_acquire(now=0.0) is True


@pytest.mark.asyncio
async def test_khoa_bucket_co_dat_ttl(redis):
    bucket = bucket_for_provider(redis, "gemini", rpm=10)
    await bucket.try_acquire(now=0.0)
    ttl = await redis.ttl(bucket._key)
    # Phải có TTL dương (không phải -1 "sống mãi mãi", không phải -2 "không tồn tại").
    assert 0 < ttl <= 3600


# --- Ruling 3: nguyên tử là MỘT lệnh gọi script, không phải cặp đọc rồi ghi ---


@pytest.mark.asyncio
async def test_moi_lan_xin_token_chi_phat_dung_mot_lenh_toi_redis(redis):
    """Chứng minh cấu trúc: try_acquire() chỉ phát MỘT lệnh cấp cao (script) tới
    Redis, không phải một cặp lệnh đọc-rồi-ghi rời rạc (HGET/GET rồi HSET/SET).

    Đây là bằng chứng tất định (đếm lệnh), không phải một test đua (race) — chạy
    lại bao nhiêu lần cũng ra cùng kết quả, khác với test dùng asyncio.gather vốn
    chỉ bắt được lỗi ngẫu nhiên một phần số lần chạy.
    """
    bucket = TokenBucket(redis, key="atomic", capacity=5, refill_per_second=0.0)
    goc = redis.execute_command
    lenh_da_phat: list[str] = []

    async def theo_doi(*args, **kwargs):
        if args:
            lenh_da_phat.append(str(args[0]).upper())
        return await goc(*args, **kwargs)

    redis.execute_command = theo_doi

    # Lần đầu: cache script phía client chưa có, redis-py có thể thử EVALSHA (miss)
    # rồi SCRIPT LOAD rồi EVALSHA — vẫn là một lần thực thi script, không lệnh nào
    # trong số đó là một lệnh đọc/ghi trực tiếp trên dữ liệu thùng token.
    await bucket.try_acquire(now=0.0)
    for ten_lenh in lenh_da_phat:
        assert ten_lenh in {"EVALSHA", "EVAL", "SCRIPT LOAD"}, (
            f"Phát hiện lệnh rời rạc ngoài script: {ten_lenh}"
        )

    # Lần thứ hai: cache đã ấm, phải đúng MỘT lệnh duy nhất cho toàn bộ việc
    # kiểm-và-trừ token.
    lenh_da_phat.clear()
    await bucket.try_acquire(now=0.0)
    assert lenh_da_phat == ["EVALSHA"]


# --- Ruling 1: Redis không hỏi được thì phải từ chối (fail closed), lỗi riêng biệt ---


class _RedisMatKetNoi:
    """Đồ giả lập một client Redis không kết nối được — dùng để kiểm hành vi
    fail-closed mà không cần dựng hạ tầng mạng thật."""

    def register_script(self, script: str):
        async def _vo_luon(*args, **kwargs):
            raise redis_exceptions.ConnectionError("giả lập mất kết nối Redis")

        return _vo_luon


@pytest.mark.asyncio
async def test_redis_khong_hoi_duoc_thi_tu_choi_thay_vi_cho_qua():
    bucket = TokenBucket(_RedisMatKetNoi(), key="x", capacity=10, refill_per_second=1.0)
    with pytest.raises(RateLimiterUnavailable):
        await bucket.try_acquire(now=0.0)


@pytest.mark.asyncio
async def test_loi_redis_khong_hoi_duoc_la_lop_rieng_khong_gia_lam_vuot_han_muc():
    bucket = TokenBucket(_RedisMatKetNoi(), key="x", capacity=10, refill_per_second=1.0)
    try:
        await bucket.try_acquire(now=0.0)
    except RateLimiterUnavailable as exc:
        # Là LLMError (thuộc cây ngoại lệ chung) nhưng KHÔNG được đội lốt một trong
        # ba lớp lỗi hạ tầng của TỪNG provider — đội lốt RateLimited sẽ khiến tầng
        # định tuyến hiểu nhầm là "nhà cung cấp đã trả lời, hãy rơi xuống dự phòng",
        # trong khi sự thật là bộ đếm hạn mức dùng chung đã chết cho MỌI provider.
        assert isinstance(exc, LLMError)
        assert not isinstance(exc, RateLimited)
        assert not isinstance(exc, QuotaExhausted)
        assert not isinstance(exc, ProviderUnavailable)
        # Thông báo phải nói rõ đây là lỗi của BỘ GIỚI HẠN, không phải "hết hạn mức".
        assert "Redis" in str(exc) or "redis" in str(exc)
        assert "hạ tầng" in str(exc) or "không phản hồi" in str(exc)
    else:
        pytest.fail("Phải ném RateLimiterUnavailable khi Redis không hồi đáp")


# --- Ruling 2: đồng hồ lấy từ Redis (TIME), không lấy từ tiến trình ứng dụng ---


@pytest.mark.asyncio
async def test_khong_truyen_now_thi_dung_dong_ho_cua_redis_khong_phai_cua_app(redis, monkeypatch):
    """fakeredis chạy trong cùng tiến trình nên lệnh TIME của nó lấy từ time.time()
    ngay trong tiến trình test — giả lập được bằng cách ghi đè đúng hàm đó, tương
    đương với việc điều khiển đồng hồ của MÁY CHỦ Redis trong đời thực.

    Nếu cài đặt lỡ dùng đồng hồ của tiến trình ứng dụng (vd time.monotonic()) khi
    now=None thay vì gọi redis.call('TIME'), việc ghi đè time.time() ở đây sẽ
    không có tác dụng gì và test này thất bại.
    """
    dong_ho = {"gia_tri": 0.0}
    monkeypatch.setattr(
        "fakeredis.commands_mixins.server_mixin.time.time",
        lambda: dong_ho["gia_tri"],
    )
    bucket = TokenBucket(redis, key="dongho", capacity=1, refill_per_second=1.0)

    assert await bucket.try_acquire() is True
    assert await bucket.try_acquire() is False  # thùng vừa cạn, đồng hồ Redis chưa trôi

    dong_ho["gia_tri"] = 5.0
    assert await bucket.try_acquire() is True  # hồi theo đồng hồ Redis đã trôi 5 giây
