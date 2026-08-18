"""Thùng token trên Redis giữ nhịp gọi provider LLM dưới hạn mức free-tier.

Hạn mức miễn phí của mỗi nhà cung cấp nhỏ, cứng, và dùng chung cho mọi người
dùng thật của ứng dụng — vượt hạn mức có thể khiến khoá bị nhà cung cấp khoá
hoặc chặn tạm thời cho TẤT CẢ mọi người, không chỉ người gây ra vượt hạn mức.
Module này là lá chắn duy nhất đứng giữa một cơn dồn dập (hoặc một vòng lặp
lỗi) và một ngày không còn LLM nào dùng được.

Việc kiểm-và-trừ token nằm trong một script Lua (_LUA) chạy nguyên tử trên
Redis — xem docstring của TokenBucket để biết vì sao KHÔNG được tách thành một
cặp lệnh đọc rồi ghi.
"""

from typing import Any

import redis.exceptions

from app.modules.llm.types import LLMError

# TTL cho một khoá thùng. Đủ dài để một provider/khoá BYOK còn đang dùng không bị
# hết hạn giữa hai lần gọi liên tiếp trong ngày; đủ ngắn để khoá của một provider
# hoặc một khoá BYOK đã ngừng dùng không tồn đọng mãi trong Redis — Redis này còn
# phục vụ những mục đích khác (phiên đăng nhập, cache...), không chỉ bộ giới hạn.
_TTL_GIAY = 3600

# Lua không có None; dùng chuỗi rỗng làm cờ báo "không ghi đè đồng hồ, hãy tự hỏi
# redis.call('TIME')". ARGV luôn là chuỗi nên đây là giá trị hợp lệ để so sánh.
_KHONG_GHI_DE_GIO = ""

_LUA = f"""
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local gio_ghi_de = ARGV[3]
local want = tonumber(ARGV[4])

-- Đồng hồ lấy từ chính MÁY CHỦ REDIS (redis.call('TIME')), không lấy từ tiến
-- trình ứng dụng đang gọi. Nhiều tiến trình/container cùng gọi một thùng dùng
-- chung; nếu mỗi tiến trình tự tính "đã trôi bao lâu" theo đồng hồ hệ điều hành
-- riêng của nó, hai đồng hồ lệch nhau sẽ khiến mỗi tiến trình tưởng thùng đã hồi
-- token ở một thời điểm khác nhau — nhân hiệu lực sức chứa lên theo số tiến
-- trình, đúng thứ thùng này sinh ra để chặn. gio_ghi_de chỉ khác rỗng khi bài
-- test cố tình ghi đè để kiểm định năng lực hồi token; mã sản phẩm không bao
-- giờ truyền nó.
local now
if gio_ghi_de == '' then
  local gio = redis.call('TIME')
  now = tonumber(gio[1]) + tonumber(gio[2]) / 1000000
else
  now = tonumber(gio_ghi_de)
end

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  ts = now
end

local troi_qua = now - ts
if troi_qua > 0 then
  tokens = math.min(capacity, tokens + troi_qua * refill)
end

local cho_phep = 0
if tokens >= want then
  tokens = tokens - want
  cho_phep = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, {_TTL_GIAY})
return cho_phep
"""


class RateLimiterUnavailable(LLMError):
    """Không hỏi được bộ đếm hạn mức — Redis không phản hồi. KHÔNG có nghĩa là đã
    vượt hạn mức; có nghĩa là bản thân bộ giới hạn đang bị hỏng/mất kết nối.

    Cố ý kế thừa THẲNG từ LLMError, không kế thừa RateLimited/QuotaExhausted/
    ProviderUnavailable — ba lớp đó mang nghĩa "provider ĐÃ trả lời (hoặc ĐÃ được
    hỏi) và trả lời là từ chối", nên tầng định tuyến phía trên coi chúng là tín
    hiệu để rơi xuống provider dự phòng. Nhưng thùng token nằm trên MỘT Redis dùng
    chung cho MỌI provider: khi Redis chết, thùng của provider kế tiếp cũng chết y
    hệt trong cùng một lượt gọi — rơi xuống dự phòng chỉ tốn thêm một lượt gọi vô
    ích trong khi phao cứu sinh đã mất cho tất cả provider cùng lúc, không riêng
    provider vừa thử. Xếp lỗi này ở một nhánh riêng của cây ngoại lệ buộc tầng
    định tuyến phải xử lý nó một cách tường minh (ví dụ: dừng ngay, không lặp qua
    hết danh sách provider), thay vì vô tình để nó lọt vào logic "thử provider
    khác" vốn viết cho lỗi hạ tầng của TỪNG provider riêng lẻ.

    Khi gặp lỗi này, TokenBucket từ chối (fail closed) thay vì cho qua không đếm:
    từ chối oan chỉ tốn một lượt thử lại của một người dùng; cho qua không đếm sẽ
    tháo bỏ lá chắn duy nhất trước hạn mức miễn phí nhỏ và dùng chung, cho phép một
    cơn dồn dập hoặc một vòng lặp lỗi tiêu hết ngân sách cả ngày của mọi người dùng
    trong vài phút — và 429 thật của nhà cung cấp chỉ tới SAU KHI hạn mức đã mất.
    """


class TokenBucket:
    """Thùng token dùng chung giữa mọi tiến trình, trạng thái nằm ở Redis.

    Việc kiểm-và-trừ token nằm gọn trong ĐÚNG MỘT lệnh gọi script Lua (_LUA) —
    không phải một cặp lệnh đọc rồi ghi (vd HGET rồi HSET) từ phía Python. Nếu
    tách thành hai lệnh riêng, hai tiến trình gọi try_acquire() gần như đồng thời
    có thể cùng đọc thấy còn token, cùng quyết định cho qua, rồi cùng ghi đè lên
    nhau — cả hai đều được cấp token dù thùng chỉ đủ cho một. Redis thực thi một
    script Lua nguyên tử (đơn luồng trong lúc chạy script), nên không có cửa sổ
    nào để một lệnh gọi try_acquire() khác xen vào giữa bước đọc và bước ghi.
    """

    def __init__(self, redis: Any, key: str, capacity: int, refill_per_second: float) -> None:
        self._redis = redis
        self._key = f"ratelimit:{key}"
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._script = redis.register_script(_LUA)

    async def try_acquire(self, tokens: int = 1, now: float | None = None) -> bool:
        """Xin `tokens` token từ thùng, trả về True nếu được cấp.

        `now` chỉ tồn tại để phục vụ test cần một đồng hồ tất định; mã sản phẩm
        LUÔN gọi hàm này KHÔNG truyền `now` (giữ mặc định None) để script tự hỏi
        đồng hồ của máy chủ Redis thay vì đồng hồ tiến trình ứng dụng — lý do nằm
        trong chú thích của _LUA.

        Redis không phản hồi được (mất kết nối, timeout...) thì ném
        RateLimiterUnavailable và TỪ CHỐI cấp token (fail closed) — không có
        chuyện coi "không hỏi được" là "còn dư token".
        """
        gio_ghi_de = _KHONG_GHI_DE_GIO if now is None else repr(now)
        try:
            cho_phep = await self._script(
                keys=[self._key],
                args=[self.capacity, self.refill_per_second, gio_ghi_de, tokens],
            )
        except redis.exceptions.RedisError as exc:
            raise RateLimiterUnavailable(
                f"Không kiểm tra được hạn mức cho khoá '{self._key}': Redis không "
                "phản hồi. Đây là lỗi hạ tầng của bộ giới hạn, không phải người "
                "dùng đã vượt hạn mức."
            ) from exc
        return bool(int(cho_phep))


def bucket_for_provider(
    redis: Any, provider_name: str, rpm: int, *, owner: str = "shared"
) -> TokenBucket:
    """Dựng thùng từ hạn mức request mỗi phút (rpm) của một nhà cung cấp.

    `owner` tách bạch hạn mức DÙNG CHUNG (mặc định "shared") khỏi hạn mức của một
    khoá BYOK (khoá API riêng của một người dùng): nếu gộp chung một thùng, lưu
    lượng dùng khoá riêng của một người sẽ ăn vào hạn mức dùng chung của mọi
    người khác, và ngược lại hạn mức dùng chung cạn có thể chặn nhầm một người
    đang trả tiền bằng khoá của chính họ.

    Khi gọi cho BYOK, `owner` PHẢI là một định danh MỜ (ví dụ băm khoá) — khoá API
    thật không bao giờ được xuất hiện trong tên khoá Redis.
    """
    return TokenBucket(
        redis,
        key=f"provider:{provider_name}:{owner}",
        capacity=rpm,
        refill_per_second=rpm / 60.0,
    )
