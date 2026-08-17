import os

import pytest

from tests.conftest import kiem_tra_ten_csdl_la_test, lay_database_url_test


def test_tu_choi_csdl_khong_ket_thuc_bang_test(monkeypatch):
    """TEST_DATABASE_URL trỏ tới một CSDL không phải CSDL test phải bị chặn.

    Bài test này chỉ gọi hàm phân tích chuỗi kết nối và kiểm tra lỗi được raise — không
    mở kết nối, không gọi drop_all, không đụng tới bất kỳ CSDL thật nào.
    """
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+asyncpg://coach:coach@localhost:5432/coach_dev"
    )
    url = lay_database_url_test()
    with pytest.raises(RuntimeError, match="_test"):
        kiem_tra_ten_csdl_la_test(url)


def test_chap_nhan_csdl_ket_thuc_bang_test(monkeypatch):
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+asyncpg://coach:coach@localhost:5432/coach_test"
    )
    url = lay_database_url_test()
    kiem_tra_ten_csdl_la_test(url)


def test_mac_dinh_khi_khong_dat_bien_moi_truong(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    url = lay_database_url_test()
    assert url == "postgresql+asyncpg://coach:coach@localhost:15432/coach_test"
    kiem_tra_ten_csdl_la_test(url)


def test_tu_choi_khi_database_url_bi_doi_giua_setup_va_teardown(monkeypatch):
    """Mô phỏng đúng kịch bản của fix teardown: nếu DATABASE_URL bị gán trực tiếp
    (không qua đường an toàn của conftest) thành một CSDL không phải CSDL test — ví dụ
    giữa lúc fixture `tao_bang` setup và teardown chạy — thì lệnh kiểm tra ở đường
    teardown (gọi cùng `kiem_tra_ten_csdl_la_test` trên `os.environ.get("DATABASE_URL")`)
    phải chặn lại.

    Test này không chạy fixture `tao_bang` thật, không mở kết nối, không gọi drop_all —
    nó chỉ tái hiện đúng lệnh gọi mà đường teardown thực thi.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://coach:coach@localhost:15432/coach")
    with pytest.raises(RuntimeError, match="_test"):
        kiem_tra_ten_csdl_la_test(os.environ.get("DATABASE_URL", ""))


def test_tu_choi_khi_database_url_bi_xoa(monkeypatch):
    """DATABASE_URL vắng mặt tại thời điểm kiểm tra phải bị chặn với thông báo rõ
    ràng bằng tiếng Việt, không phải KeyError khó hiểu.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="_test"):
        kiem_tra_ten_csdl_la_test(os.environ.get("DATABASE_URL", ""))
