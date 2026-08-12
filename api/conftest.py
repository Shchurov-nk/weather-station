import os

# Must be set before app/config are imported: Settings() reads env at import.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SENSOR_TOKEN", "test-token")
