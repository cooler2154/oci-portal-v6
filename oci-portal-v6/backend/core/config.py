# backend/core/config.py
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_ENV:                  str = "development"
    SECRET_KEY:               str = "change-me-use-secrets-token-hex-32"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 8
    DATABASE_URL:             str = "sqlite+aiosqlite:///./oci_portal.db"
    OCI_INSTANCE_PRINCIPAL:   int = 0   # 0 = ~/.oci/config   1 = InstancePrincipal
    ALLOWED_ORIGINS:          str = "http://localhost:8000,http://127.0.0.1:8000"
    LOG_LEVEL:                str = "DEBUG"
    LOG_FILE:                 str = "debug.log"
    AUDIT_LOG_FILE:           str = "audit.log"
    
    # JDE Cache Management Configuration
    CACHE_API_BASE:           str = "http://10.20.0.99:8999/manage/mgmtrestservice"
    CACHE_API_USER:           str = "jde_admin"
    CACHE_API_PASSWORD:       str = "jde_admin"

    @property
    def origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file       = ".env"
        case_sensitive = True


settings = Settings()
