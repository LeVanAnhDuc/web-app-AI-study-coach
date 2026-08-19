# Bàn giao — AI Study Coach, sau giai đoạn M0 + M1

> File này để một phiên làm việc sau (có thể trên máy khác) đọc là hiểu và làm tiếp được.
> Cập nhật: 2026-08-19. Trạng thái: `main` = `d899721`, 301 test qua, `ruff check .` 0 lỗi toàn repo.

---

## Mục lục

1. [Chạy được trong 5 phút](#1-chạy-được-trong-5-phút)
2. [Sản phẩm này là gì](#2-sản-phẩm-này-là-gì)
3. [Đã xây xong những gì](#3-đã-xây-xong-những-gì)
4. [Bất biến chịu lực — đọc trước khi sửa code](#4-bất-biến-chịu-lực--đọc-trước-khi-sửa-code)
5. [Việc tiếp theo](#5-việc-tiếp-theo)
6. [Khoảng trống đã biết](#6-khoảng-trống-đã-biết)
7. [Cách làm việc đã dùng](#7-cách-làm-việc-đã-dùng)
8. [Tài liệu liên quan](#8-tài-liệu-liên-quan)

---

## 1. Chạy được trong 5 phút

### Hạ tầng cục bộ

```bash
docker compose up -d          # Postgres ở cổng 15432, Redis ở 6379
```

**Cổng Postgres là 15432, không phải 5432.** Máy phát triển ban đầu đã có PostgreSQL native chiếm 5432, 5433 và 55432. Quyết định lúc đó: không bao giờ tắt hay sửa service hệ thống của người dùng, chỉ đổi cổng phía Docker. Nếu máy mới của bạn trống cổng 5432 thì vẫn cứ dùng 15432 để khỏi lệch với `.env.example` và `conftest.py`.

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# .venv/bin/python -m pip install -e ".[dev]"         # Linux/macOS

cp ../.env.example .env        # rồi điền JWT_SECRET và LLM_KEY_ENCRYPTION_KEY

.venv/Scripts/alembic.exe upgrade head
.venv/Scripts/python.exe -m pytest -q                 # kỳ vọng: 301 passed
.venv/Scripts/python.exe -m ruff check .              # kỳ vọng: 0 lỗi
```

`LLM_KEY_ENCRYPTION_KEY` phải là **đúng 32 byte** sau khi decode base64. Sinh một khoá:

```bash
.venv/Scripts/python.exe -c "from app.modules.llm.keyvault import generate_master_key; print(generate_master_key())"
```

Không cấu hình cũng chạy được (BYOK chưa bật), nhưng cấu hình **sai độ dài** thì app hỏng ngay lúc khởi động — có chủ đích, xem §4.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local     # BACKEND_URL=http://localhost:8000
npm run dev
```

### Lưu ý khi chạy lệnh

- **Chạy `ruff` từ `backend/`.** Có `ruff.toml` ở gốc repo chỉ để loại `docs/` khỏi phạm vi, vì `ruff format` có định dạng lại các khối mã Python trong file Markdown và đã từng ghi đè hai tài liệu kế hoạch. Đừng thêm quy tắc nào vào file đó — cấu hình lint thật chỉ có một bản ở `backend/pyproject.toml`.
- **Test cần Postgres thật.** `conftest.py` bắt buộc tên CSDL kết thúc bằng `_test` và sẽ `raise RuntimeError` nếu không — chốt chống xoá CSDL phát triển, đừng nới.
- **Console Windows (cp1252):** in tiếng Việt ra stdout có thể ném `UnicodeEncodeError`. Khi viết script chẩn đoán, hãy `assert` trong Python hoặc ghi file UTF-8 thay vì `print`.

---

## 2. Sản phẩm này là gì

Gia sư AI cá nhân hoá. Điểm phân biệt: nó **theo dõi quá trình học và chủ động điều chỉnh kế hoạch**, không chỉ trả lời câu hỏi.

Luồng: đặt mục tiêu → AI lập lộ trình → học → làm bài → AI đánh giá → theo dõi tiến độ → **điều chỉnh lộ trình**.

Các quyết định định hình sản phẩm (đã chốt, đừng mở lại nếu không có lý do mới):

| | Quyết định |
|---|---|
| Mục đích | Sản phẩm thật có người dùng thật, không phải demo |
| Nguồn nội dung | **AI tự sinh toàn bộ.** Không RAG trên tài liệu người dùng |
| Phạm vi chủ đề | Mở, nhưng UI dẫn người dùng vào các track chủ đề sẵn |
| Vòng lõi | Bài học có cấu trúc làm trục, tutor chat hỗ trợ bên cạnh |
| Kiến trúc nội dung | Sinh bộ xương lộ trình trước, sinh nội dung bài học **lười** và cache lại |
| Điều chỉnh lộ trình | **Luật cứng** (R1–R4), không dùng LLM để phán xét |
| Chi phí LLM | **Chạy free tier** ngay cả khi có người dùng thật, cộng BYOK |
| Hướng UI | Hướng **C — "Đường leo"** (ẩn dụ mặt cắt độ cao) |

### Hệ quả bảo mật của việc chọn free tier

Người dùng đã được cảnh báo và vẫn chọn free tier. Vì dữ liệu prompt trên free tier **có thể được dùng để huấn luyện mô hình bên thứ ba**:

- **Không định danh nào được vào prompt** — không email, không tên, không `user_id` thật. Chỉ id ẩn danh.
- Phải **công bố rõ** trong Điều khoản/Chính sách và một dòng ở onboarding.

Đây là ràng buộc còn hiệu lực, không phải ghi chú lịch sử.

---

## 3. Đã xây xong những gì

### M0 — Khung, xác thực, frontend BFF

```
backend/app/
  main.py            FastAPI app, /health, handler 422 có che trường bí mật
  config.py          Settings (pydantic-settings)
  db.py              engine async, session_factory, Base
  models.py          ĐIỂM ĐĂNG KÝ MODEL DUY NHẤT — xem §4
  security.py        argon2 + JWT (PyJWT HS256)
  modules/auth/      router, service, deps, models, schemas
alembic/versions/    0001 users · 0002 refresh_tokens · 0003 token_ledger
```

```
frontend/
  app/api/auth/{register,login,logout,refresh}/route.ts   BFF route handlers
  app/{login,register,dashboard}/                          trang
  lib/session.ts     cookie httpOnly (sc_access, sc_refresh)
  lib/backend.ts     BACKEND_URL — server-only, KHÔNG có tiền tố NEXT_PUBLIC_
```

Next.js làm **BFF**: JWT chỉ sống trong cookie `httpOnly`, JavaScript trong trình duyệt không bao giờ đọc được.

### M1 — Tầng LLM đa provider

```
backend/app/modules/llm/
  types.py         CallSpec, Usage, Capability, cây lỗi LLMError
  registry.py      prompt + model đầu ra Pydantic cho từng TaskType
  schema_util.py   Pydantic JSON Schema -> schema provider chấp nhận được
  providers/
    base.py        Protocol Provider
    gemini.py      Gemini — provider DUY NHẤT ép JSON schema bản địa
    openai_compat.py  lớp cơ sở tương thích OpenAI
    groq.py  mistral.py
  fixtures.py      ghi/phát lại fixture (off / record / replay)
  degrade.py       tầng hạ cấp JSON: coerce -> validate -> retry
  ratelimit.py     token bucket bằng Lua trên Redis
  keyvault.py       két khoá BYOK bằng AES-GCM
  ledger.py        sổ ghi token
  routing.py       chọn provider + rơi xuống dự phòng
  service.py       LLMService — MẶT TIỀN DUY NHẤT, xem §4
backend/scripts/
  measure_json_compliance.py   script đo tuân thủ schema
```

**Luồng một lời gọi:** `LLMService.run()` → `LLMRouter` (hỏi token bucket trước mỗi provider) → `complete_structured()` (hạ cấp + retry khi sai schema) → `provider.complete()` → ghi sổ theo từng provider.

---

## 4. Bất biến chịu lực — đọc trước khi sửa code

Đây là phần quan trọng nhất của file này. Mỗi mục dưới đây là một thứ **sẽ hỏng trong im lặng** nếu sửa mà không biết. Tất cả đều đã có comment tại chỗ trong mã; danh sách này để bạn biết chúng tồn tại.

### 4.1 Mọi tầng phải ghi usage của **mọi** lượt gọi

Chủ đề này tái diễn **sáu lần** trong M1 ở sáu chỗ khác nhau, và luôn lệch về **một chiều duy nhất**: app trông rẻ hơn thực tế, đúng đến ngày quota cạn sớm hơn dự báo.

- `complete_structured()` trả về **danh sách** `Usage`, một phần tử cho mỗi lượt thử, kể cả lượt sai schema.
- `usages` được khai ở **gốc** cây `LLMError`, không phải trên từng lớp con — để một điểm ném lỗi mới không thể quên mang nó.
- Khi gắn usages vào một exception, luôn **cộng**: `exc.usages = usages + exc.usages`. **Đừng gán.** Một phép gán sẽ xoá phần mà adapter đã gắn tại chỗ ném. Lỗi này đã xảy ra một lần và chỉ lộ ra khi kiểm tới dòng sổ thật.
- `record_usage()` **từ chối** (`ValueError`) danh sách usage trộn nhiều provider. Người gọi phải gom theo `(provider, model)` rồi gọi một lần cho mỗi nhóm. Router mới là lớp biết usage nào của provider nào.
- Phải ghi sổ **cả trên đường thất bại**: `AllProvidersFailed` mang usages của mọi lượt trong chuỗi.

### 4.2 Phân loại exception là luồng điều khiển của router

| Lớp lỗi | Router làm gì |
|---|---|
| `RateLimited`, `QuotaExhausted`, `ProviderUnavailable`, `SchemaViolation` | **Rơi xuống** provider dự phòng |
| Bucket từ chối | **Rơi xuống** (bucket theo từng provider, đầy ở đây không nói gì về provider khác) |
| `RateLimiterUnavailable` | **Nổi lên, KHÔNG rơi xuống dự phòng** |

`RateLimiterUnavailable` là **anh em** của các lớp kia, cố ý không kế thừa chúng, đúng để router phân biệt được. Nó nghĩa là *không hỏi được* bộ giới hạn. Rơi xuống trong trạng thái đó = gọi **không đo đếm** lần lượt tới từng provider, đúng cái chạy loạn mà bucket sinh ra để chặn.

Đừng thêm `except LLMError` hay `except Exception` rộng ở bất kỳ đâu trong `routing.py`. Hiện cả file chỉ có **một** khối `except` cho nhóm rơi-xuống, cộng một khối gắn-usages-rồi-ném-lại.

**Không bao giờ `sleep` theo `retry_after`.** Toàn bộ lý do có dự phòng là đi ngay chỗ khác. `retry_after` là thông tin để ghi lại, không phải lệnh chờ.

### 4.3 Chỗ nào không kiểm chứng được thì nghiêng về phía rẻ-nếu-sai

Nguyên tắc này được dùng năm lần. Hai chiều sai gần như chưa bao giờ đối xứng:

- **Redis chết → từ chối** (fail closed). Từ chối sai làm một người thử lại một lần; cho qua sai mất chốt duy nhất giữ hạn mức dùng chung.
- **429 không rõ → `RateLimited`**, chỉ chọn `QuotaExhausted` khi có bằng chứng dương tính về hết hạn mức ngày. Sai kiểu sau làm **mất Gemini cả ngày** — provider duy nhất ép được schema.
- **Không kiểm được năng lực provider → khai yếu hơn.** Groq/Mistral hiện khai `frozenset()` rỗng. `response_format: json_object` là JSON *mode*: chỉ bảo đảm cú pháp hợp lệ, **không** bảo đảm khớp schema.
- **Cờ `capabilities` là dữ liệu vào của định tuyến.** Một cờ nói sai tệ hơn một cờ thiếu. Đừng khai `STREAMING` khi chưa hiện thực streaming.

Khi bạn viết một mặc định kiểu này, hãy ghi tính bất đối xứng vào comment, và đặt mặc định ở **chỗ gọi** (nhánh rơi xuống sau `if`) chứ không chôn trong hàm phụ — để một lần sửa hàm phụ về sau không thể lặng lẽ đảo chiều nhánh an toàn.

### 4.4 Session của sổ ghi token

`record_usage()` **tự commit transaction của nó**, vì một lần ghi sổ lỗi không được phá huỷ một câu trả lời đã tiêu token — khả năng thất bại độc lập đòi một transaction độc lập.

Hệ quả: nó phải nhận một session **riêng**. `LLMService` tự mở session bằng `session_factory` cho việc này, và `run()` **không nhận** tham số session. Đừng thêm lại — một tham số nhận mà không dùng hàm ý session của người gọi có vai trò và mời người sau nối lại sự phụ thuộc đó.

Nó bắt `(SQLAlchemyError, OSError)` — `OSError` là cần thiết vì `ConnectionRefusedError` **không** phải `SQLAlchemyError`. Và `rollback()` bên trong khối `except` được bọc riêng, vì trên CSDL đã chết `rollback()` đi lại đúng con đường vừa hỏng nên cũng ném.

### 4.5 `app/models.py` là điểm đăng ký model duy nhất

`alembic/env.py` và `tests/conftest.py` **chỉ** import file này. **Đừng xoá dòng import nào trong đó**, kể cả khi linter báo "unused".

Hậu quả nếu xoá không phải một lỗi ồn ào: `alembic revision --autogenerate` sẽ coi bảng đó là không còn được khai báo và **sinh ra migration chứa `DROP TABLE`** kèm mọi index — migration đó chạy `upgrade` sạch và review nhanh dễ lọt. Trong test, bảng có thể vẫn tồn tại "nhờ may mắn" nếu một file test khác tình cờ import trước.

`tests/test_models.py` ghim danh sách tên bảng để việc này đỏ ngay tại đó.

### 4.6 Bí mật không bao giờ vào thông báo lỗi

Lỗ này xuất hiện **ba lần** ở ba đường khác nhau. Ba luật rút ra:

1. **Đừng kiểm giá trị bí mật bằng validator của pydantic.** `ValidationError` dội giá trị vi phạm vào `str(exc)`. Viết mã kiểm thường, tự soạn thông báo — xem `_kiem_tra_hinh_dang_khoa_goc` trong `keyvault.py` làm mẫu. Điều này áp cho `jwt_secret` khi nào bạn thêm kiểm độ dài: **cách hiển nhiên (`Field(min_length=32)`) là cách sai.**
2. **Handler 422 phải che cả lỗi cấp thân request.** Khi thân sai kiểu, pydantic báo `loc: ["body"]` và `input` = toàn bộ thân. Che theo `len(loc) <= 1` **và** đi đệ quy vào `input`.
3. **Trên đường lỗi mạng dùng `type(exc).__name__`, không `str(exc)`** — repr của exception httpx có thể mang theo URL, mà URL có thể mang khoá.
4. **Đừng log `exc.errors()` của một `ValidationError` từ `Settings`.** Đo được ngày 2026-08-19: khi thiếu một biến bắt buộc (ví dụ `DATABASE_URL`), `exc.errors()` chứa **nguyên văn khoá API của mọi provider** đang có trong môi trường, vì pydantic đưa cả dict giá trị vào `input_value`. Điểm bẫy: `str(exc)`, `repr(exc)` và traceback đều **sạch** (pydantic cắt bớt dict repr), nên kiểm nhanh sẽ kết luận là an toàn. Hiện chưa chỗ nào gọi `.errors()` lên lỗi này — nhưng thêm log lỗi cấu hình lúc khởi động là việc rất tự nhiên, và đó là lúc mọi khoá provider vào log.

Khoá API đi trong **header** (`x-goog-api-key`, `Authorization: Bearer`), không bao giờ trong query string — query string là chỗ dễ rơi vào log nhất một request.

### 4.7 Két khoá AES-GCM

- **Nonce mới, ngẫu nhiên thật, mỗi lần mã hoá.** Dùng lại cặp (khoá, nonce) trong GCM là **phá vỡ**, không phải làm yếu. Lưu ý về kiểm thử: **test round-trip không bắt được nonce cố định** — test chịu lực là mã hoá cùng bản rõ hai lần rồi so hai khối.
- Khối lưu là `base64(version[1] || nonce[12] || ciphertext || tag)`. **Byte phiên bản tồn tại có mục đích:** khi M8 thêm AAD, tag xác thực sẽ phụ thuộc AAD nên mọi khối cũ sẽ thất bại xác thực. Có byte phiên bản thì đó là một cuộc di trú sạch, không phải ngày cắt.
- **Khi thêm AAD, byte phiên bản PHẢI nằm trong chính AAD** (`AAD = version || user_id || provider`). Nếu không, kẻ có quyền ghi CSDL lật version từ 2 về 1 để ép đi nhánh không-AAD — hạ cấp mất chính lớp bảo vệ vừa thêm.
- Phép kiểm "đúng 32 byte" **không** phải lớp đai dư: `AESGCM` im lặng nhận cả khoá 16 và 24 byte (kích thước hợp lệ của AES-128/192), nên thiếu nó thì một cấu hình sai sẽ âm thầm hạ cấp độ mạnh mã hoá mãi mãi.

### 4.8 Token bucket

- **Thời gian lấy từ `redis.call('TIME')`**, không từ tiến trình app. Với nhiều tiến trình, mỗi tiến trình nạp lại bucket theo đồng hồ riêng — **sức chứa hiệu dụng nhân lên theo số tiến trình**, âm thầm.
- Tham số `now_override_for_tests` là keyword-only và được đặt tên để tự cảnh báo. **Mã sản phẩm không bao giờ truyền nó.**
- Toàn bộ kiểm-và-trừ nằm trong **một** script Lua. Đừng tách thành đọc-rồi-ghi.
- Bucket **chỉ chặn theo phút**, không theo ngày. Xem §6.

### 4.9 Tầng hạ cấp JSON

- `complete_structured()` bắt **đúng** `ValidationError`, không bắt thêm `ValueError`. Điều này chịu lực trên một bất biến: `model_validate_json` là **điểm parse JSON duy nhất** và nó ném `ValidationError` (không phải `JSONDecodeError`) khi chuỗi không parse được. **Nếu đổi sang `json.loads` + `model_validate` thì phải mở rộng khối except.**
- Coercion chỉ cắt code fence và prose. **Đừng vá JSON méo bằng cách đoán** — một phép đoán biến đầu ra hỏng thành dữ liệu *hợp lệ nhưng sai*, rồi nó đi vào ứng dụng như giá trị đã kiểm.
- Lỗi hạ tầng **không bao giờ được retry** ở tầng này. Khối `try` quanh `provider.complete()` chỉ gắn usages rồi `raise` lại — không `continue`, không nuốt, không đổi kiểu.

### 4.10 Bẫy của `FakeProvider` trong test

`backend/tests/llm/fakes.py` có bốn tính chất mà **năm task khác dựa vào**: `calls` được append **trước** mọi lần raise; một `None` trong `errors` tiêu một suất mà không ném; `responses` rỗng thì trả `"{}"`; `aclose` đặt `closed = True`. Đừng đổi.

Và cái bẫy: `FakeProvider` nhận `name` và `capabilities` qua constructor, nên **test có thể bịa ra tập năng lực nào cũng được và vẫn xanh trong khi dây nối thật đã sai**. Đã có các test đọc năng lực và tên từ **lớp adapter thật** để chặn việc này. Nếu bạn thêm logic phụ thuộc tên hoặc năng lực provider, hãy thêm một test cùng kiểu.

---

## 5. Việc tiếp theo

### 5.1 Chạy phép đo tuân thủ schema — việc đáng làm đầu tiên

Đây là lý do M1 tồn tại, và nó **chưa chạy** vì cần khoá API thật và tiêu hạn mức miễn phí trong ngày.

```bash
cd backend        # cần .env đã có ở đây (xem §1) — script đọc Settings đầy đủ

# Chạy thử ngoại tuyến trước. Cần khoá GIẢ để dựng provider, vì build_providers()
# chỉ tạo provider nào có khoá khác rỗng:
LLM_FIXTURE_MODE=replay GEMINI_API_KEY=dummy \
  .venv/Scripts/python.exe -m scripts.measure_json_compliance --live --lan 3

# Phép đo thật:
.venv/Scripts/python.exe -m scripts.measure_json_compliance --live --lan 50

# Đo thêm tỉ lệ sau khi qua tầng hạ cấp (tốn THÊM một loạt lượt gọi):
.venv/Scripts/python.exe -m scripts.measure_json_compliance --live --lan 50 --do-ca-sau-ha-cap
```

Cả `--lan`, `--live`, `--do-ca-sau-ha-cap` đã kiểm lại đúng tên cờ. Không có `.env` thì script vỡ ngay ở bước đọc `Settings` với lỗi thiếu `DATABASE_URL`/`REDIS_URL`/`JWT_SECRET` — không phải lỗi của script.

Cần biết trước:

- Mặc định `--lan 50` × 7 tác vụ ≈ **350 lượt gọi mỗi provider**. Script hãm nhịp theo `PROVIDER_RPM` nên riêng Gemini mất **≥35 phút**. Nó in ước lượng trước khi bắt đầu.
- Script đo **provider thô** (`provider.complete()` một lượt, prompt nguyên văn từ registry), **không** qua tầng hạ cấp — vì thang retry và phần chỉ dẫn JSON chèn vào prompt sẽ che mất khác biệt giữa các provider, và con số thu được sẽ mô tả tầng hạ cấp của mình chứ không mô tả provider. Số "sau khi qua tầng hạ cấp" là một cờ riêng, báo cáo ở mục riêng.
- Kết quả ghi ra `docs/design/`, định dạng Markdown ổn định để diff được, có tên model và ngày.
- Ở chế độ replay, **fixture thiếu làm script hỏng to tiếng** thay vì đếm như "provider bận" — vì ở chế độ đó fixture thiếu luôn là lỗi người vận hành, không bao giờ là kết quả hợp lệ để lấy trung bình.

**Kết quả dùng để làm gì:** thay hai bảng `ROUTING` và `PROVIDER_RPM` trong `routing.py` (hiện là giá trị tạm chưa kiểm chứng, đã ghi chú rõ trong mã), và quyết định có nâng cờ `STRUCTURED_OUTPUT` cho Groq/Mistral hay không. Cập nhật cả §7 của spec.

### 5.2 Đóng ba hạng mục chưa kiểm chứng

Một lượt gọi thật đóng được cả ba:

| Hạng mục | Tình trạng |
|---|---|
| Header `x-goog-api-key` | Cài theo tài liệu, chưa gọi thật để xác nhận. Nếu không hoạt động, rơi về query param **và ghi rõ** |
| Tên model `gemini-2.5-flash` | Chưa xác nhận qua endpoint liệt kê model. **Đừng thay bằng tên nhớ được** — tên sai làm mọi lượt gọi thất bại, và một tên nghe hợp lý sẽ che mất đúng chỗ đó |
| Câu chữ body lỗi 429 | `_co_bang_chung_het_han_muc_ngay` khớp trên phỏng đoán. Có mẫu thật thì sửa lại |

### 5.3 Thêm CI

Chưa có `.github/`. Hiện tính chất "test không bao giờ gọi API thật" chỉ được bảo đảm bởi `addopts = "-m 'not live'"` trong `pyproject.toml` cộng việc chạy tay, và 301 test không được nơi nào cưỡng chế.

**Cảnh báo cho người viết workflow:** nếu bạn đặt `pytest -m ''` thì chốt loại-trừ-test-live bị vô hiệu trong im lặng và CI sẽ gọi provider thật. Ghi chú điều này ngay trong file workflow.

### 5.4 M2 trở đi

Xem §12 của spec (`docs/superpowers/specs/2026-08-17-ai-study-coach-design.md`). Tóm lại:

- **M2** — onboarding: đặt mục tiêu + placement quiz, theo hướng UI C ("Đường leo"). Mockup có ở `docs/design/mockups/m2-directions.html`.
- **M3** — sinh lộ trình và nội dung bài học (lười + cache theo `content_key`).
- **M4** — quiz và chấm điểm. **Nhớ lớp phòng chống prompt-injection thứ ba:** khi `matched_criteria` rỗng thì kẹp điểm `≤ 0.5` ở tầng ứng dụng. Đây là lớp duy nhất mà prompt không thể lách được — hai lớp kia (khung prompt, structured output) đều có thể bị chính văn bản đang được chấm lật. Đã có comment cạnh `GradeOut` trong `registry.py`.
- **M5** — dashboard tiến độ. **M6** — luật điều chỉnh lộ trình R1–R4 kèm chặn trôi. **M7** — spaced repetition. **M8** — BYOK (nơi két khoá có người tiêu thụ đầu tiên, và nơi thêm AAD).

---

## 6. Khoảng trống đã biết

Không phải khiếm khuyết — là những thứ đã quyết định hoãn, ghi lại để bạn biết chúng tồn tại.

| Hạng mục | Chi tiết |
|---|---|
| Cầu dao hạn mức **ngày** | Bucket chỉ chặn theo phút: `capacity=rpm`, `refill=rpm/60` mỗi giây, tức khoảng **14.400 lượt Gemini/ngày** ở `rpm=10` — cao hơn nhiều mọi hạn mức ngày hợp lý. `QuotaExhausted` và `RateLimited` **hiện hành xử giống nhau**; phép phân loại được giữ để một bộ nhớ hạn mức ngày ở mốc sau dùng. Bốn việc cụ thể đã ghi cạnh `PROVIDER_RPM` |
| Tự động làm mới token | Chưa có. Người dùng **phải đăng nhập lại sau 15 phút** không hoạt động |
| Giới hạn tốc độ `/login` | Chưa có, cũng chưa có lockout. argon2 làm nó *chậm*, không làm nó *an toàn*. Token bucket ở M1 dùng được ngay |
| Dọn `refresh_tokens` | Mỗi lần đăng nhập thêm một dòng, chưa có gì xoá dòng hết hạn hoặc đã thu hồi |
| Thu hồi toàn bộ khi phát hiện phát lại | Dùng lại một refresh token **đã thu hồi** là tín hiệu bị đánh cắp → nên thu hồi mọi token của người đó. Có comment cạnh nhánh `user_id is None` trong `auth/service.py` |
| `min_length` cho `jwt_secret` | Cố ý chưa thêm. Khi thêm, **phải viết mã kiểm thường** — xem §4.6 |
| Ràng AAD cho két khoá | Hoãn tới M8. Byte phiên bản đã có sẵn để việc này là migration sạch |
| `maxAge` cookie ở frontend | Hằng số 30 ngày trong `lib/session.ts` trùng lặp `jwt_refresh_ttl_seconds` mà không có nguồn dùng chung |
| Event loop dùng chung cho cả session test | Rủi ro đã chấp nhận: nếu một test để lại task nền, nó có thể ảnh hưởng test sau. Hiện chưa test nào làm vậy |

---

## 7. Cách làm việc đã dùng

M0/M1 được thực thi theo **subagent-driven development**: mỗi task một agent mới, mỗi task một vòng review độc lập, vòng sửa nếu cần, rồi re-review có phạm vi. 20 task, 53 commit.

Nếu bạn tiếp tục theo cách này, ba điều đã tỏ ra đáng giá nhất:

### 7.1 "Test đã qua" không bao giờ là bằng chứng

Một test phải được chứng minh là **đỏ** với mã hỏng trước khi nó được tin. Trong M0/M1: một tuyên bố A/B phủ năm test hoá ra sai với một test; một test do kế hoạch bắt buộc lại đậu với **cả** mã đúng và mã hỏng; một bộ quét tự nhận phủ "mọi đường lỗi" bỏ sót hai đường mới nhất.

### 7.2 Câu hỏi mặc định khi đọc một test

**Test này tiêm cái gì, và cái đó có phải chính cái mã xử lý đúng không?**

Khuôn mẫu này bắt được ba lỗi Critical trong M0/M1 — mỗi lần là một test xanh chứng nhận **điều ngược lại** với những gì mã làm:

- test bắt "CSDL chết không phá huỷ câu trả lời" tiêm `OperationalError` — đúng lớp duy nhất *được* bắt;
- test che 422 chỉ dùng lỗi cấp trường, không dùng lỗi cấp thân;
- test cho `rollback` monkeypatch nó bằng một giả lập **luôn thành công**.

### 7.3 Phần lớn lỗi quan trọng nằm trong mã mẫu của kế hoạch

Không phải do người thực thi làm sai. Kế hoạch chứa: một nonce lấy từ đồng hồ app (gây lệch giữa nhiều tiến trình), một đường gọi bỏ qua hoàn toàn bộ giới hạn tốc độ, một hàm xoá tên thuộc tính khi chuyển JSON Schema, một test bắt buộc mà không phân biệt được đúng/sai, và một chuỗi prompt thiếu tiền tố `f`.

Vòng review là thứ bắt được chúng. Và một loại lỗi chỉ lộ ra ở review **toàn nhánh**: hai bản sửa cách nhau nhiều vòng, mỗi bản đúng khi được review riêng, gặp nhau và thành lỗi mất dữ liệu.

Quy ước: **comment, docstring và commit message viết tiếng Việt**; định danh công khai tiếng Anh, hàm phụ private đặt tên tiếng Việt.

---

## 8. Tài liệu liên quan

| Đường dẫn | Nội dung |
|---|---|
| `docs/superpowers/specs/2026-08-17-ai-study-coach-design.md` | Spec thiết kế đã duyệt — 13 mục, quyết định D1–D8, luật điều chỉnh R1–R4, rủi ro R-1..R-7, mốc M0–M8 |
| `docs/superpowers/plans/2026-08-17-m0-m1-khung-va-tang-llm.md` | Kế hoạch triển khai M0/M1, 20 task. **Lưu ý: nhiều đoạn mã mẫu trong đó có lỗi** đã được sửa trong repo — nơi nào lệch thì tin repo |
| `docs/superpowers/so-quyet-dinh-m0-m1.md` | **Sổ 66 phán quyết** trong lúc thực thi, kèm lý do và chi phí nếu sai. Là nơi ghi *vì sao* mã có hình dạng như vậy |
| `docs/design/mockups/m2-directions.html` | 3 hướng UI × 3 màn hình. Hướng **C** đã được chọn |

Bảng token màu của hướng C:

```
sky #F2F7F6 · slope #2C7A72 · slope-light #8FC4BC · deep #123A38
coral #E9614C (CHỈ dùng cho bài học bị đổi/đường vòng) · sand #E8D9B5 · line #D3E2DE
```
