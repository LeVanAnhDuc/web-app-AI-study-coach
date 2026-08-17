import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.auth.models import User


@pytest.mark.asyncio
async def test_luu_va_doc_lai_user(db_session):
    user = User(email="an@vidu.vn", password_hash="bam-gia")
    db_session.add(user)
    await db_session.commit()

    found = await db_session.scalar(select(User).where(User.email == "an@vidu.vn"))
    assert found is not None
    assert isinstance(found.id, uuid.UUID)
    assert found.created_at is not None


@pytest.mark.asyncio
async def test_email_khong_duoc_trung(db_session):
    db_session.add(User(email="binh@vidu.vn", password_hash="a"))
    await db_session.commit()

    db_session.add(User(email="binh@vidu.vn", password_hash="b"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
