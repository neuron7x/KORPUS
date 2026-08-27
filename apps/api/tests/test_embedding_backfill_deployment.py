import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_cloud_run_backfill_is_bounded_singleton_and_explicitly_enabled() -> None:
    job = (ROOT / "infra/gcp/runtime/embedding_backfill.tf").read_text()
    assert "var.embedding_backfill_enabled ? 1 : 0" in job
    assert "task_count  = 1" in job
    assert "parallelism = 1" in job
    assert "max_retries           = 0" in job
    assert "tostring(var.embedding_backfill_batch_size)" in job
    assert "tostring(var.embedding_backfill_max_batches)" in job
    assert re.search(r"image\s+= var\.api_image", job)
    assert "KORPUS_RUNTIME_IMAGE_REF = var.api_image" in job


def test_cloud_run_backfill_reads_token_from_secret_file_only() -> None:
    job = (ROOT / "infra/gcp/runtime/embedding_backfill.tf").read_text()
    assert re.search(r"secret\s+= var\.embedding_token_secret_id", job)
    assert 'KORPUS_EMBEDDING_TOKEN_FILE = "/secrets/embedding/token"' in job
    assert "KORPUS_EMBEDDING_TOKEN =" not in job
    assert "service_account       = local.service_accounts.worker" in job
    assert 'mount_path = "/etc/korpus/governance"' in job
