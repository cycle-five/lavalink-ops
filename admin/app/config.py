from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    admin_password: str
    admin_secret_key: str
    admin_port: int = 8080
    # Set to true when the admin panel is served over HTTPS (reverse proxy,
    # real TLS on 8080, etc). Leave false for the SSH-tunnel default — a
    # Secure cookie won't be sent over plain HTTP and you'd be locked out.
    admin_cookie_secure: bool = False
    
    # Host networking is the supported deployment, so services colocate on
    # 127.0.0.1. docker-compose still sets these explicitly; the defaults
    # are here as a safety net.
    lavalink_host: str = "127.0.0.1"
    lavalink_port: int = 2333
    lavalink_password: str
    lavalink_container_name: str = "lavalink"

    cipher_host: str = "127.0.0.1"
    cipher_port: int = 8001

    bgutil_host: str = "127.0.0.1"
    bgutil_port: int = 4416
    
    pot_refresh_enabled: bool = True
    pot_refresh_interval_hours: int = 6
    
    config_path: str = "/config/application.yml"
    state_path: str = "/state/state.json"

    @property
    def lavalink_url(self) -> str:
        return f"http://{self.lavalink_host}:{self.lavalink_port}"
    
    @property
    def cipher_url(self) -> str:
        return f"http://{self.cipher_host}:{self.cipher_port}"
    
    @property
    def bgutil_url(self) -> str:
        return f"http://{self.bgutil_host}:{self.bgutil_port}"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8"
    }
