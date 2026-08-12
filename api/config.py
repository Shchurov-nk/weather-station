from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Read from env vars; missing ones fail at startup, not on the first request."""

    database_url: str
    sensor_token: str


settings = Settings()
