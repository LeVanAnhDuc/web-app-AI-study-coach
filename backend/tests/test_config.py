from app.config import Settings


def test_settings_doc_duoc_tu_bien_moi_truong(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/1")
    monkeypatch.setenv("JWT_SECRET", "bi-mat")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert settings.redis_url == "redis://h:6379/1"
    assert settings.jwt_access_ttl_seconds == 900


def test_settings_co_gia_tri_mac_dinh_cho_ttl_refresh(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/1")
    monkeypatch.setenv("JWT_SECRET", "bi-mat")
    settings = Settings(_env_file=None)
    assert settings.jwt_refresh_ttl_seconds == 60 * 60 * 24 * 30
