# app/core/config/loader.py

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from .models import (
    AppConfig, CloudinaryConfig, GeneralConfig, HostingConfig, CookieConfig,
    # ContentDeliveryConfig, S3ApiConfig,
    DatabaseConfig, RedisConfig, S3Config,
    SecurityConfig, OAuthConfig, OAuthProviderConfig, AIConfig, ChromaDBConfig, MailConfig,
    PaymentsConfig, StorageConfig, StripeConfig, PaystackConfig, MonitoringConfig,
    LoggingConfig, BackgroundTasksConfig, SupabaseStorageConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded OAuth provider metadata (never changes per environment)
# ---------------------------------------------------------------------------
OAUTH_REGISTRY: Dict[str, Dict[str, Any]] = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scopes": ["openid", "email", "profile"],
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "emails_url": "https://api.github.com/user/emails",
        "scopes": ["read:user", "user:email"],
    },
    "facebook": {
        "authorize_url": "https://www.facebook.com/v18.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v18.0/oauth/access_token",
        "userinfo_url": "https://graph.facebook.com/v18.0/me",
        "scopes": ["email", "public_profile"],
    },
    "linkedin": {
        "authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "userinfo_url": "https://api.linkedin.com/v2/me?projection=(id,localizedFirstName,localizedLastName)",
        "scopes": ["openid", "profile", "email"],
    },
}


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
    # def _str(self, v): return str(v)
    def _int(self, v): return int(v)
    def _float(self, v): return float(v)
    def _list(self, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return v
        return []

    # def _load_oauth_providers(self) -> Dict[str, OAuthProviderConfig]:
    #     """Build enabled provider map from APP_* env vars.
    #     A provider is enabled ONLY when both CLIENT_ID and CLIENT_SECRET exist."""
    #     enabled: Dict[str, OAuthProviderConfig] = {}

    #     # (provider_key, client_id_env_name, client_secret_env_name)
    #     providers = [
    #         ("google", "APP_GOOGLE_CLIENT_ID", "APP_GOOGLE_CLIENT_SECRET"),
    #         ("github", "APP_GITHUB_CLIENT_ID", "APP_GITHUB_CLIENT_SECRET"),
    #         ("facebook", "APP_FACEBOOK_CLIENT_ID", "APP_FACEBOOK_CLIENT_SECRET"),
    #         ("linkedin", "APP_LINKEDIN_CLIENT_ID", "APP_LINKEDIN_CLIENT_SECRET"),
    #     ]

    #     for name, id_key, secret_key in providers:
    #         client_id = self._get(id_key)
    #         client_secret = self._get(secret_key)

    #         if not client_id or not client_secret:
    #             logger.debug(f"OAuth provider '{name}' disabled — missing {id_key} or {secret_key}")
    #             continue

    #         meta = OAUTH_REGISTRY[name]
    #         enabled[name] = OAuthProviderConfig(
    #             client_id=client_id,
    #             client_secret=client_secret,
    #             authorize_url=meta["authorize_url"],
    #             token_url=meta["token_url"],
    #             userinfo_url=meta["userinfo_url"],
    #             scopes=meta.get("scopes", []),
    #             emails_url=meta.get("emails_url"),
    #         )
    #         logger.info(f"OAuth provider ready: {name}")

    #     return enabled

    # # v2
    # def _load_oauth_providers(self) -> Dict[str, OAuthProviderConfig]:
    #     enabled: Dict[str, OAuthProviderConfig] = {}

    #     providers = [
    #         ("google", "APP_GOOGLE_CLIENT_ID", "APP_GOOGLE_CLIENT_SECRET", "APP_GOOGLE_REDIRECT_URI"),
    #         ("github", "APP_GITHUB_CLIENT_ID", "APP_GITHUB_CLIENT_SECRET", "APP_GITHUB_REDIRECT_URI"),
    #         ("facebook", "APP_FACEBOOK_CLIENT_ID", "APP_FACEBOOK_CLIENT_SECRET", "APP_FACEBOOK_REDIRECT_URI"),
    #         ("linkedin", "APP_LINKEDIN_CLIENT_ID", "APP_LINKEDIN_CLIENT_SECRET", "APP_LINKEDIN_REDIRECT_URI"),
    #     ]

    #     for name, id_key, secret_key, redirect_key in providers:
    #         client_id = self._get(id_key)
    #         client_secret = self._get(secret_key)

    #         if not client_id or not client_secret:
    #             logger.debug(f"OAuth provider '{name}' disabled — missing {id_key} or {secret_key}")
    #             continue

    #         meta = OAUTH_REGISTRY[name]
    #         enabled[name] = OAuthProviderConfig(
    #             client_id=client_id,
    #             client_secret=client_secret,
    #             authorize_url=meta["authorize_url"],
    #             token_url=meta["token_url"],
    #             userinfo_url=meta["userinfo_url"],
    #             scopes=meta.get("scopes", []),
    #             emails_url=meta.get("emails_url"),
    #             redirect_uri=self._get(redirect_key),   # ← NEW: None if not set
    #         )
    #         logger.info(f"OAuth provider ready: {name}")

    #     return enabled

    # v3
    # app/core/config/loader.py

    def _is_dummy_value(self, value: Optional[str]) -> bool:
        """Detect placeholder / dummy OAuth credentials."""
        if not value or len(value.strip()) < 8:
            return True
        lowered = value.strip().lower()
        markers = (
            "dummy", "test", "placeholder", "your_", "changeme",
            "xxx", "todo", "pending", "replace", "sample",
            "example", "fake", "mock", "null", "none",
        )
        return any(m in lowered for m in markers)

    def _load_oauth_providers(self) -> Dict[str, OAuthProviderConfig]:
        enabled: Dict[str, OAuthProviderConfig] = {}

        providers = [
            ("google",    "APP_GOOGLE_CLIENT_ID",    "APP_GOOGLE_CLIENT_SECRET",    "APP_GOOGLE_REDIRECT_URI"),
            ("github",    "APP_GITHUB_CLIENT_ID",    "APP_GITHUB_CLIENT_SECRET",    "APP_GITHUB_REDIRECT_URI"),
            ("facebook",  "APP_FACEBOOK_CLIENT_ID",  "APP_FACEBOOK_CLIENT_SECRET",  "APP_FACEBOOK_REDIRECT_URI"),
            ("linkedin",  "APP_LINKEDIN_CLIENT_ID",  "APP_LINKEDIN_CLIENT_SECRET",  "APP_LINKEDIN_REDIRECT_URI"),
        ]

        for name, id_key, secret_key, redirect_key in providers:
            client_id     = self._get(id_key)
            client_secret = self._get(secret_key)

            if not client_id or not client_secret:
                logger.debug(f"OAuth provider '{name}' disabled — missing {id_key} or {secret_key}")
                continue

            if self._is_dummy_value(client_id) or self._is_dummy_value(client_secret):
                logger.warning(f"OAuth provider '{name}' disabled — dummy credentials detected")
                continue

            meta = OAUTH_REGISTRY[name]
            enabled[name] = OAuthProviderConfig(
                client_id=client_id,
                client_secret=client_secret,
                authorize_url=meta["authorize_url"],
                token_url=meta["token_url"],
                userinfo_url=meta["userinfo_url"],
                scopes=meta.get("scopes", []),
                emails_url=meta.get("emails_url"),
                redirect_uri=self._get(redirect_key),
            )
            logger.info(f"OAuth provider ready: {name}")

        return enabled


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
                api_url=self._get("APP_API_URL"),  # ← alias maps to api_url_override
                # content_delivery=ContentDeliveryConfig(
                #     type=self._get("APP_CONTENT_DELIVERY_TYPE", "filesystem"),
                #     filesystem_base_path=self._get("APP_FILESYSTEM_BASE_PATH", "./uploads"),
                #     max_file_size_mb=self._get("APP_MAX_FILE_SIZE_MB", 500, self._int),
                # ),
                cookie_config=CookieConfig(
                    domain=self._get("APP_COOKIE_DOMAIN", "localhost"),
                    secure=self._get("APP_COOKIE_SECURE", False, self._bool),
                    samesite=self._get("APP_COOKIE_SAMESITE", "lax"),
                ),
            ),
                
            storage_config=StorageConfig(
                
                provider=self._get("APP_STORAGE_PROVIDER", "supabase"),
                
                # max_file_size_mb=self._int("APP_MAX_FILE_SIZE_MB", 50),
                max_file_size_mb=self._get("APP_MAX_FILE_SIZE_MB", 50, self._int),
                
                allowed_image_types=self._get(
                    "APP_ALLOWED_IMAGE_TYPES",
                    ["image/jpeg", "image/png", "image/webp", "image/gif"],
                    self._list,
                ),

                allowed_video_types=self._get(
                    "APP_ALLOWED_VIDEO_TYPES",
                    ["video/mp4", "video/webm"],
                    self._list,
                ),
                
                filesystem_base_path=self._get("APP_FILESYSTEM_BASE_PATH", "./uploads"),
                
                s3=S3Config(
                    bucket_name=self._get("APP_S3_BUCKET_NAME"),
                    endpoint_url=self._get("APP_S3_ENDPOINT_URL"),
                    region=self._get("APP_S3_REGION", "us-east-1"),
                    access_key_id=self._get("APP_S3_ACCESS_KEY_ID"),
                    secret_access_key=self._get("APP_S3_SECRET_ACCESS_KEY"),
                ),
                
                supabase=SupabaseStorageConfig(
                    url=self._get("APP_SUPABASE_URL"),
                    service_role_key=self._get("APP_SUPABASE_SERVICE_ROLE_KEY"),
                    bucket_name=self._get("APP_SUPABASE_BUCKET", "courses", str),
                    public=self._get("APP_SUPABASE_BUCKET_PUBLIC", True, self._bool),
                ),
                
                cloudinary=CloudinaryConfig(
                    cloud_name=self._get("APP_CLOUDINARY_CLOUD_NAME"),
                    api_key=self._get("APP_CLOUDINARY_API_KEY"),
                    api_secret=self._get("APP_CLOUDINARY_API_SECRET"),
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
                # Configurable list of super-admin emails (can impersonate / bypass some guards)
                super_admin_emails=self._get("APP_SUPER_ADMIN_EMAILS", [], self._list),
                signup_otp_ttl_seconds=self._get("APP_SIGNUP_OTP_TTL_SECONDS", 600, self._int),
                password_reset_otp_ttl_seconds=self._get("APP_PASSWORD_RESET_OTP_TTL_SECONDS", 900, self._int),
            ),
            
            oauth_config=OAuthConfig(
                google_client_id=self._get("APP_GOOGLE_CLIENT_ID"),
                google_client_secret=self._get("APP_GOOGLE_CLIENT_SECRET"),
                google_redirect_uri=self._get("APP_GOOGLE_REDIRECT_URI"),
                facebook_client_id=self._get("APP_FACEBOOK_CLIENT_ID"),
                facebook_client_secret=self._get("APP_FACEBOOK_CLIENT_SECRET"),
                facebook_redirect_uri=self._get("APP_FACEBOOK_REDIRECT_URI"),
                twitter_client_id=self._get("APP_TWITTER_CLIENT_ID"),
                twitter_client_secret=self._get("APP_TWITTER_CLIENT_SECRET"),
                twitter_redirect_uri=self._get("APP_TWITTER_REDIRECT_URI"),
                github_client_id=self._get("APP_GITHUB_CLIENT_ID"),
                github_client_secret=self._get("APP_GITHUB_CLIENT_SECRET"),
                github_redirect_uri=self._get("APP_GITHUB_REDIRECT_URI"),
                linkedin_client_id=self._get("APP_LINKEDIN_CLIENT_ID"),
                linkedin_client_secret=self._get("APP_LINKEDIN_CLIENT_SECRET"),
                linkedin_redirect_uri=self._get("APP_LINKEDIN_REDIRECT_URI"),
            ),
            
            oauth_provider_config=self._load_oauth_providers(),
            
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

