"""Pin cho điểm đăng ký model duy nhất `app.models` (review Task 17, mục 2).

Test CHỈ import `app.models` — không import trực tiếp `app.modules.auth.models`
hay `app.modules.llm.ledger` — đúng như cách `alembic/env.py` và
`tests/conftest.py` đăng ký metadata trong thực tế. Nếu một dòng import bị xoá
khỏi `app/models.py` (kể cả do một lượt "dọn dẹp unused import"), bảng tương
ứng biến mất khỏi `Base.metadata` và test này phải ĐỎ ngay tại đây — thay vì
để lộ ra sau này qua một migration autogenerate chứa `DROP TABLE`.
"""

import app.models


def test_moi_bang_duoc_dang_ky_qua_app_models():
    ten_bang = set(app.models.Base.metadata.tables.keys())
    assert {"users", "refresh_tokens", "token_ledger"} <= ten_bang
