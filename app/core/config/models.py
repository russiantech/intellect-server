from typing import Dict, Literal, Optional, List
from pydantic import BaseModel, Field, computed_field


class GeneralConfig(BaseModel):
    development_mode: bool = True
    install_mode: bool = False
    api_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    site_name: str = "Intellect"
    site_description: str = "Intellect – Your Digital Learning Companion"
    contact_email: str = "info@intellect.ng"
    timezone: str = "Africa/Lagos"
    whatsapp_community_link: str = ""


class CookieConfig(BaseModel):
    domain: str = "localhost"
    secure: bool = False
    httponly: bool = True
    samesite: Literal["lax", "strict", "none"] = "lax"
    max_age: int = 60 * 60 * 24 * 7


# class S3ApiConfig(BaseModel):
#     bucket_name: Optional[str] = None
#     endpoint_url: Optional[str] = None
#     region: str = "us-east-1"
#     access_key_id: Optional[str] = None
#     secret_access_key: Optional[str] = None
#     use_ssl: bool = True
#     signature_version: str = "s3v4"

# v2
class S3Config(BaseModel):
    bucket_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: str = "us-east-1"
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    use_ssl: bool = True

class SupabaseStorageConfig(BaseModel):
    url: Optional[str] = None
    service_role_key: Optional[str] = None
    bucket_name: str = "products"
    public: bool = True


class CloudinaryConfig(BaseModel):
    cloud_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    folder: str = "products"

class StorageConfig(BaseModel):
    """Single source of truth for file storage: where files live,
    how they're validated, and provider-specific credentials.
    Add new providers as sibling sub-models (s3, cloudinary, supabase, ...)."""
    provider: Literal["filesystem", "s3", "supabase", "cloudinary"] = "supabase"

    # Validation — applies regardless of provider
    max_file_size_mb: int = 50
    allowed_image_types: List[str] = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    allowed_video_types: List[str] = ["video/mp4", "video/webm"]

    # Filesystem provider
    filesystem_base_path: str = "./uploads"

    # Provider-specific credentials
    s3: S3Config = S3Config()
    supabase: SupabaseStorageConfig = SupabaseStorageConfig()
    cloudinary: CloudinaryConfig = CloudinaryConfig()


# class ContentDeliveryConfig(BaseModel):
#     type: Literal["filesystem", "s3api", "cloudinary"] = "filesystem"
#     filesystem_base_path: str = "./uploads"
#     max_file_size_mb: int = 500
#     allowed_file_types: List[str] = [
#         "video/mp4", "video/webm", "video/ogg",
#         "image/jpeg", "image/png", "image/gif", "image/webp",
#         "application/pdf",
#         "application/vnd.ms-powerpoint",
#         "application/vnd.openxmlformats-officedocument.presentationml.presentation",
#         "application/msword",
#         "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#         "audio/mpeg", "audio/wav",
#     ]
#     s3api: S3ApiConfig = S3ApiConfig()


class HostingConfig(BaseModel):
    domain: str = "localhost"
    ssl: bool = False
    port: int = 8000
    use_default_org: bool = True
    allowed_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    allowed_regexp: str = ""
    self_hosted: bool = True
    frontend_url: str = "http://localhost:5173"
    # Proper field for override — loaded by loader.py like everything else
    api_url_override: Optional[str] = Field(default=None, alias="api_url")
    cookie_config: CookieConfig = CookieConfig()
    # content_delivery: ContentDeliveryConfig = ContentDeliveryConfig()

    @computed_field
    @property
    def api_url(self) -> str:
        if self.api_url_override is not None:
            return self.api_url_override.rstrip("/")
        scheme = "https" if self.ssl else "http"
        if (self.ssl and self.port == 443) or (not self.ssl and self.port == 80):
            return f"{scheme}://{self.domain}"
        return f"{scheme}://{self.domain}:{self.port}"


class DatabaseConfig(BaseModel):
    sql_connection_string: Optional[str] = None
    pool_size: int = 20
    max_overflow: int = 40
    pool_recycle: int = 3600
    pool_timeout: int = 30
    echo: bool = False


class RedisConfig(BaseModel):
    redis_connection_string: Optional[str] = None
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    username: Optional[str] = None
    ssl: bool = False
    ssl_cert_reqs: Optional[str] = None
    connection_pool_size: int = 10
    socket_timeout: int = 5
    socket_connect_timeout: int = 5
    retry_on_timeout: bool = True
    decode_responses: bool = True
    default_ttl: int = 3600
    session_ttl: int = 86400
    rate_limit_ttl: int = 60
    use_sentinel: bool = False
    sentinel_nodes: List = []
    sentinel_service_name: str = "mymaster"
    sentinel_password: Optional[str] = None


class SecurityConfig(BaseModel):
    auth_jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    refresh_token_expire_minutes: int = 60 * 24 * 7
    jwt_secret_key: str = "FALLBACK_SECRET"
    password_reset_token_expire_minutes: int = 15
    email_verification_token_expire_minutes: int = 60 * 24
    bcrypt_rounds: int = 12
    # cors_allowed_origins: List[str] = ["http://localhost:5173"]
    cors_allowed_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    super_admin_emails: List[str] = Field(default_factory=list)  # ← NEW: list of emails that can impersonate
    # OTP settings
    signup_otp_ttl_seconds: int = 600          # 10 min pending signup window
    password_reset_otp_ttl_seconds: int = 900  # 15 min reset code



class OAuthConfig(BaseModel):
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[str] = None

    facebook_client_id: Optional[str] = None
    facebook_client_secret: Optional[str] = None
    facebook_redirect_uri: Optional[str] = None

    twitter_client_id: Optional[str] = None
    twitter_client_secret: Optional[str] = None
    twitter_redirect_uri: Optional[str] = None

    # --- NEW ---
    github_client_id: Optional[str] = None
    github_client_secret: Optional[str] = None
    github_redirect_uri: Optional[str] = None

    linkedin_client_id: Optional[str] = None
    linkedin_client_secret: Optional[str] = None
    linkedin_redirect_uri: Optional[str] = None


# class OAuthProviderConfig(BaseModel):
#     """Runtime provider bundle (secrets + hardcoded URLs)."""
#     client_id: str
#     client_secret: str
#     authorize_url: str
#     token_url: str
#     userinfo_url: str
#     scopes: List[str] = Field(default_factory=list)
#     emails_url: Optional[str] = None   # GitHub only


class OAuthProviderConfig(BaseModel):
    """Runtime provider bundle (secrets + hardcoded URLs + optional redirect override)."""
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: List[str] = Field(default_factory=list)
    emails_url: Optional[str] = None
    redirect_uri: Optional[str] = None   # ← NEW: per-provider override from env
    
class ChromaDBConfig(BaseModel):
    is_separate_database_enabled: bool = False
    db_host: Optional[str] = None
    persist_directory: str = "./chromadb_data"
    collection_name: str = "intellect_documents"


class AIConfig(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    is_ai_enabled: bool = False
    default_model: str = "claude-sonnet-4-20250514"
    embedding_model: str = "text-embedding-ada-002"
    chromadb_config: ChromaDBConfig = ChromaDBConfig()


class MailConfig(BaseModel):
    system_email_address: str = "no-reply@intellect.ng"
    mail_sender_name: str = "Intellect"
    mail_sender_email: str = "no-reply@salesnet.ng"
    provider: Literal["smtp", "resend", "sendgrid", "mailgun", "console"] = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout: int = 30
    resend_api_key: Optional[str] = None
    sendgrid_api_key: Optional[str] = None
    mailgun_api_key: Optional[str] = None
    mailgun_domain: Optional[str] = None
    templates_dir: str = "./app/templates/email"
    emails_per_hour: int = 100
    retry_attempts: int = 3


class PaystackConfig(BaseModel):
    secret_key: Optional[str] = None
    public_key: Optional[str] = None
    base_url: str = "https://api.paystack.co"
    callback_url: Optional[str] = None
    timeout: int = 30


class StripeConfig(BaseModel):
    secret_key: Optional[str] = None
    publishable_key: Optional[str] = None
    webhook_standard_secret: Optional[str] = None
    webhook_connect_secret: Optional[str] = None
    client_id: Optional[str] = None
    api_version: str = "2023-10-16"
    max_network_retries: int = 2
    timeout: int = 30


class PaymentsConfig(BaseModel):
    default_provider: Literal["stripe", "paystack", "none"] = "none"
    currency: str = "NGN"
    stripe: StripeConfig = StripeConfig()
    paystack: PaystackConfig = PaystackConfig()


class MonitoringConfig(BaseModel):
    sentry_dsn: Optional[str] = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 1.0
    sentry_profiles_sample_rate: float = 1.0
    enable_health_checks: bool = True
    enable_metrics: bool = False
    metrics_port: int = 9090


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    file_path: str = "./logs/app.log"
    max_file_size_mb: int = 100
    backup_count: int = 5
    enable_json_logs: bool = False
    enable_sql_logging: bool = False


class BackgroundTasksConfig(BaseModel):
    enabled: bool = True
    max_workers: int = 4
    queue_max_size: int = 100
    retry_attempts: int = 3
    retry_delay_seconds: int = 5


class AppConfig(BaseModel):
    general_config: GeneralConfig = GeneralConfig()
    hosting_config: HostingConfig = HostingConfig()
    storage_config: StorageConfig = StorageConfig()
    database_config: DatabaseConfig = DatabaseConfig()
    redis_config: RedisConfig = RedisConfig()
    security_config: SecurityConfig
    oauth_config: OAuthConfig = OAuthConfig()
    oauth_provider_config: Dict[str, OAuthProviderConfig] = Field(default_factory=dict)
    ai_config: AIConfig = AIConfig()
    mail_config: MailConfig = MailConfig()
    payments_config: PaymentsConfig = PaymentsConfig()
    monitoring_config: MonitoringConfig = MonitoringConfig()
    logging_config: LoggingConfig = LoggingConfig()
    background_tasks_config: BackgroundTasksConfig = BackgroundTasksConfig()
    
    @computed_field
    @property
    def cors_origins(self) -> List[str]:
        """Unified CORS origins from hosting config."""
        origins = self.hosting_config.allowed_origins
        if not origins:
            return ["http://localhost:5173"]
        return origins
    
    # class Config:
    #     env_prefix = "INTELLECT_"
    #     env_file = ".env"
