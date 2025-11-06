"""Pydantic settings for common restapi options."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class OIDC(BaseSettings):
    """Settings relating to OIDC authentication."""

    def __init__(self):
        super().__init__()
        if self.discovery_url:
            raise Exception(f"discovery_url must not be set: {self.discovery_url}")
        self.discovery_url = f"{self.authority_url}/.well-known/openid-configuration"

    # Base path providing endpoint for /.well-known/openid-configuration
    # Not including /.well-known/ to align with Azul web.
    authority_url: str = "http://localhost:8080/auth/realms/azul"
    discovery_url: str = ""
    client_id: str = "web"
    scopes: str = "openid profile email offline_access"
    roles_key: str = "roles"
    username_key: str = "preferred_username"
    cache_ttl: int = 600
    swagger_redirect_url: str = "/api/oauth2-redirect"
    model_config = SettingsConfigDict(env_prefix="oidc_")


class Cors(BaseSettings):
    """Settings for cross origin resources."""

    allow_origins: list[str] = []
    allow_methods: list[str] = []
    allow_headers: list[str] = []
    allow_credentials: bool = False
    model_config = SettingsConfigDict(env_prefix="cors_")


class Restapi(BaseSettings):
    """Settings for restapi specific bindings."""

    host: str = "localhost"
    port: int = 8080
    workers: int = 1
    asyncio_workers: int = 4
    reload: bool = False
    prefix: str = "/api"
    root_path: str = "/"
    security: str = "none"
    headers: dict[str, str] = dict()
    model_config = SettingsConfigDict(env_prefix="restapi_")


class Logging(BaseSettings):
    """Logger configuration."""

    log_file: str = ""
    log_format: str = (
        "level=<level>{level: <8}</level> time=<green>{time:YYYY-MM-DDTHH:mm:ss.SS}</green> "
        "name=<cyan>{name}</cyan> function=<cyan>{function}</cyan> {message}"
    )
    log_level: str = "info"
    log_retention: str = "1 months"
    log_rotation: str = "daily"
    log_backtrace: bool = False
    # get temp dir
    audit_file: str = os.path.join(os.getcwd(), "logs", "restapi-audit.log")
    audit_format: str = (
        "full_time={time:%d/%b/%Y:%H:%M:%S.%f} client_ip={client_ip} client_port={client_port} "
        "connection={connection} username={username} method={method} "
        'path={path} generic_path={generic_path} status={status_code} user_agent="{user_agent}" '
        'referer={referer} duration_ms={duration_ms} security="{security}"'
    )
    audit_retention: str = "1 months"
    audit_rotation: str = "daily"
    audit_path_filter: list[str] = ["/metrics"]
    model_config = SettingsConfigDict(env_prefix="logger_")


oidc = OIDC()
restapi = Restapi()
cors = Cors()
logging = Logging()


def reset():
    """Reset the configuration objects."""
    global restapi, cors, logging, oidc
    oidc = OIDC()
    restapi = Restapi()
    cors = Cors()
    logging = Logging()
