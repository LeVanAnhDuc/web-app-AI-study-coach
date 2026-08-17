import pytest

from tests.conftest import kiem_tra_ten_csdl_la_test, lay_database_url_test


def test_tu_choi_csdl_khong_ket_thuc_bang_test(monkeypatch):
    """TEST_DATABASE_URL trỏ tới một CSDL không phải CSDL test phải bị chặn.

    Bài test này chỉ gọi hàm phân tích chuỗi kết nối và kiểm tra assert — không mở kết
    nối, không gọi drop_all, không đụng tới bất kỳ CSDL thật nào.
    """
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql+asyncpg://coach:coach@localhost:5432/coach_dev"
    )
    url = lay_database_url_test()
    with pytest.raises(AssertionError, match="_test"):
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
