from korpus.config import get_settings
from korpus.infrastructure.repository import SqlRepository

settings = get_settings()
repository = SqlRepository(settings.database_url, settings.resolved_audit_hmac_key)
repository.initialize()
result = repository.verify_audit()
print(result.model_dump_json(indent=2))
raise SystemExit(0 if result.valid else 1)
