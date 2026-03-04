from core.audit import AuditService
from core.celery_app import celery_app


@celery_app.task(name="sentinel_rag.purge_expired_audit_responses")
def purge_expired_audit_responses_task() -> dict[str, int]:
    service = AuditService()
    purged = service.purge_expired_response_bodies()
    return {"purged": purged}
