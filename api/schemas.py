from pydantic import BaseModel, Field


class SensorReading(BaseModel):
    """Bounds mirror the DB CHECK constraints (BME280 datasheet range):
    pydantic gives the client a readable 422, the CHECKs stay as the
    last line of defense if the API is ever bypassed."""

    temp: float = Field(ge=-40, le=85)
    hum: float = Field(ge=0, le=100)
    pres: float = Field(ge=300, le=1100)
