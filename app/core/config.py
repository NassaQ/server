from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field
from urllib.parse import quote_plus

class Settings(BaseSettings):
    MONGO_USER: str
    MONGO_PASS: str
    MONGO_HOST: str
    MONGO_PORT: int = 10260
    MONGO_DB_NAME: str = "sdmsdb"
    MONGO_TLS_INSECURE: bool = True
    
    SQL_SERVER: str
    SQL_DB_NAME: str
    SQL_USER: str
    SQL_PASS: str
    SQL_DRIVER: str = "ODBC Driver 18 for SQL Server"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @computed_field
    def MONGO_CONNECTION_STRING(self) -> str:
        encoded_pass = quote_plus(self.MONGO_PASS)
        return (
            f"mongodb://{self.MONGO_USER}:{encoded_pass}@{self.MONGO_HOST}:{self.MONGO_PORT}/"
            f"?ssl=true&tlsInsecure={str(self.MONGO_TLS_INSECURE).lower()}"
            "&authMechanism=SCRAM-SHA-256&retrywrites=false"
            "&maxIdleTimeMS=120000&serverSelectionTimeoutMS=30000"
        )

    @computed_field
    def SQL_CONNECTION_STRING(self) -> str:
        encoded_pass = quote_plus(self.SQL_PASS)
        
        return (
            f"mssql+aioodbc://{self.SQL_USER}:{encoded_pass}@"
            f"{self.SQL_SERVER}/{self.SQL_DB_NAME}"
            f"?driver={quote_plus(self.SQL_DRIVER)}"
            "&TrustServerCertificate=yes"
        )

settings = Settings() # type: ignore