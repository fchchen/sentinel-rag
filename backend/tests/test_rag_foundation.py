from core.rag import DocumentRegistry, DocumentStatus


def test_new_document_starts_in_pending_state() -> None:
    registry = DocumentRegistry()

    document = registry.register_document(
        tenant_id="tenant-a",
        filename="runbook.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )

    assert document.status is DocumentStatus.PENDING


def test_malware_detected_sets_status_quarantined() -> None:
    registry = DocumentRegistry()
    document = registry.register_document(
        tenant_id="tenant-a",
        filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )

    updated = registry.apply_scan_result(document.id, "malware")

    assert updated.status is DocumentStatus.QUARANTINED


def test_only_active_documents_indexed_by_rag_pipeline() -> None:
    registry = DocumentRegistry()
    active = registry.register_document(
        tenant_id="tenant-a",
        filename="guide.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )
    quarantined = registry.register_document(
        tenant_id="tenant-a",
        filename="bad.pdf",
        mime_type="application/pdf",
        size_bytes=4096,
    )

    registry.apply_scan_result(active.id, "clean")
    registry.apply_scan_result(quarantined.id, "malware")

    retrievable = registry.retrievable_documents(tenant_id="tenant-a")

    assert [document.id for document in retrievable] == [active.id]
