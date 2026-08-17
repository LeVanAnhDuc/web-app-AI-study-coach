import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.security import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_bam_mat_khau_roi_kiem_lai_thanh_cong():
    hashed = hash_password("mat-khau-rat-manh")
    assert hashed != "mat-khau-rat-manh"
    assert verify_password("mat-khau-rat-manh", hashed) is True


def test_mat_khau_sai_thi_khong_khop():
    hashed = hash_password("mat-khau-rat-manh")
    assert verify_password("mat-khau-khac", hashed) is False


def test_hai_lan_bam_cung_mat_khau_ra_hai_chuoi_khac_nhau():
    assert hash_password("giong-nhau") != hash_password("giong-nhau")


def test_phat_va_giai_ma_token():
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    token = create_access_token(user_id, now)
    assert decode_access_token(token, now) == user_id


def test_token_het_han_thi_bao_loi():
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    token = create_access_token(user_id, now)
    later = now + timedelta(seconds=901)
    with pytest.raises(InvalidToken):
        decode_access_token(token, later)


def test_token_bi_sua_thi_bao_loi():
    token = create_access_token(uuid.uuid4(), datetime.now(UTC))
    with pytest.raises(InvalidToken):
        decode_access_token(token + "x", datetime.now(UTC))
