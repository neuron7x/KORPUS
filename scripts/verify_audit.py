from korpus.config import get_settings
from korpus.infrastructure.runtime import create_repository

settings = get_settings()
repository = create_repository(settings)
repository.initialize()
result = repository.verify_audit()
print(result.model_dump_json(indent=2))
raise SystemExit(0 if result.valid else 1)
