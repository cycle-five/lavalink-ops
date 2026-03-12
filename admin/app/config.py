from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    admin_password: str
    admin_secret_key: str
    admin_port: int = 8080
    
    lavalink_host: str = "lavalink"
    lavalink_port: int = 2333
    lavalink_password: str
    lavalink_container_name: str = "lavalink"
    
    cipher_host: str = "yt-cipher"
    cipher_port: int = 8001
    
    bgutil_host: str = "bgutil-pot"
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
