import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from .models import (
    AppConfig, GeneralConfig, HostingConfig, CookieConfig,
    ContentDeliveryConfig, S3ApiConfig, DatabaseConfig, RedisConfig,
    SecurityConfig, OAuthConfig, AIConfig, ChromaDBConfig, MailConfig,
    PaymentsConfig, StripeConfig, PaystackConfig, MonitoringConfig,
    LoggingConfig, BackgroundTasksConfig,
)


class ConfigLoader:
    def __init__(self):
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent.parent
        dotenv_path = project_root / ".env"
        load_dotenv(dotenv_path, override=True)

    def _get(self, key: str, default: Any = None, cast=None) -> Any:
        val = os.environ.get(key)
        if val in [None, "", "None"]:
            return default
        if cast:
            try:
                return cast(val)
            except Exception:
                return default
        return val

    def _bool(self, v): return str(v).lower() in ("true", "1", "yes")
    def _int(self, v): return int(v)
    def _float(self, v): return float(v)
    # def _list(self, v): return [x.strip() for x in str(v).split(",") if x.strip()] if isinstance(v, str) else v or []
    def _list(self, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return v
        return []

    def load_config(self) -> AppConfig:
        secret = self._get("APP_AUTH_JWT_SECRET_KEY")
        if not secret:
            raise ValueError("APP_AUTH_JWT_SECRET_KEY is required in .env")

        return AppConfig(
            general_config=GeneralConfig(
                development_mode=self._get("APP_DEVELOPMENT_MODE", True, self._bool),
                api_prefix=self._get("APP_API_PREFIX", "/api/v1"),
                site_name=self._get("APP_SITE_NAME", "Intellect"),
                site_description=self._get("APP_SITE_DESCRIPTION", "Intellect – Your Digital Learning Companion"),
                contact_email=self._get("APP_CONTACT_EMAIL", "hello@intellect.ng"),
                timezone=self._get("APP_TIMEZONE", "Africa/Lagos"),
                whatsapp_community_link=self._get("APP_WHATSAPP_COMMUNITY_LINK", ""),
            ),
            hosting_config=HostingConfig(
                domain=self._get("APP_DOMAIN", "localhost"),
                port=self._get("APP_PORT", 8000, self._int),
                ssl=self._get("APP_SSL", False, self._bool),
                frontend_url=self._get("APP_FRONTEND_URL", "http://localhost:5173"),
                # allowed_origins=self._get("APP_ALLOWED_ORIGINS", ["http://localhost:5173"], self._list),
                content_delivery=ContentDeliveryConfig(
                    type=self._get("APP_CONTENT_DELIVERY_TYPE", "filesystem"),
                    filesystem_base_path=self._get("APP_FILESYSTEM_BASE_PATH", "./uploads"),
                    max_file_size_mb=self._get("APP_MAX_FILE_SIZE_MB", 500, self._int),
                ),
                cookie_config=CookieConfig(
                    domain=self._get("APP_COOKIE_DOMAIN", "localhost"),
                    secure=self._get("APP_COOKIE_SECURE", False, self._bool),
                    samesite=self._get("APP_COOKIE_SAMESITE", "lax"),
                ),
            ),
            database_config=DatabaseConfig(
                sql_connection_string=self._get("APP_SQL_CONNECTION_STRING"),
                pool_size=self._get("APP_DB_POOL_SIZE", 20, self._int),
                max_overflow=self._get("APP_DB_MAX_OVERFLOW", 40, self._int),
                echo=self._get("APP_DB_ECHO", False, self._bool),
            ),
            redis_config=RedisConfig(
                redis_connection_string=self._get("APP_REDIS_CONNECTION_STRING"),
                host=self._get("APP_REDIS_HOST", "localhost"),
                port=self._get("APP_REDIS_PORT", 6379, self._int),
                password=self._get("APP_REDIS_PASSWORD"),
            ),
            security_config=SecurityConfig(
                auth_jwt_secret_key=secret,
                jwt_algorithm=self._get("APP_JWT_ALGORITHM", "HS256"),
                access_token_expire_minutes=self._get("APP_ACCESS_TOKEN_EXPIRE_MINUTES", 1440, self._int),
                refresh_token_expire_minutes=self._get("APP_REFRESH_TOKEN_EXPIRE_MINUTES", 10080, self._int),
                password_reset_token_expire_minutes=self._get("APP_PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", 15, self._int),
                email_verification_token_expire_minutes=self._get("APP_EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES", 1440, self._int),
                cors_allowed_origins=self._get("APP_ALLOWED_ORIGINS", ["http://localhost:5173"], self._list),
            ),
            oauth_config=OAuthConfig(
                google_client_id=self._get("APP_GOOGLE_CLIENT_ID"),
                google_client_secret=self._get("APP_GOOGLE_CLIENT_SECRET"),
            ),
            ai_config=AIConfig(
                anthropic_api_key=self._get("APP_ANTHROPIC_API_KEY"),
                openai_api_key=self._get("APP_OPENAI_API_KEY"),
                is_ai_enabled=self._get("APP_IS_AI_ENABLED", False, self._bool),
                default_model=self._get("APP_DEFAULT_AI_MODEL", "claude-sonnet-4-20250514"),
            ),
            mail_config=MailConfig(
                provider=self._get("APP_MAIL_PROVIDER", "console"),
                resend_api_key=self._get("APP_RESEND_API_KEY"),
                mail_sender_name=self._get("APP_MAIL_SENDER_NAME", "Intellect"),
                mail_sender_email=self._get("APP_MAIL_SENDER_EMAIL", "no-reply@intellect.ng"),
                system_email_address=self._get("APP_SYSTEM_EMAIL_ADDRESS", "no-reply@intellect.ng"),
                smtp_host=self._get("APP_SMTP_HOST", "smtp.gmail.com"),
                smtp_port=self._get("APP_SMTP_PORT", 587, self._int),
                smtp_username=self._get("APP_SMTP_USERNAME"),
                smtp_password=self._get("APP_SMTP_PASSWORD"),
                smtp_use_tls=self._get("APP_SMTP_USE_TLS", True, self._bool),
            ),
            payments_config=PaymentsConfig(
                default_provider=self._get("APP_PAYMENTS_DEFAULT_PROVIDER", "none"),
                currency=self._get("APP_PAYMENTS_CURRENCY", "NGN"),
                paystack=PaystackConfig(
                    secret_key=self._get("APP_PAYSTACK_SECRET_KEY"),
                    public_key=self._get("APP_PAYSTACK_PUBLIC_KEY"),
                    callback_url=self._get("APP_PAYSTACK_CALLBACK_URL"),
                ),
                stripe=StripeConfig(
                    secret_key=self._get("APP_STRIPE_SECRET_KEY"),
                    publishable_key=self._get("APP_STRIPE_PUBLISHABLE_KEY"),
                ),
            ),
        )
