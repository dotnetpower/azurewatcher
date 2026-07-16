"""Production document-ingestion composition tests."""

from __future__ import annotations

import pytest

from fdai.delivery.ingestion_gateway.prod import ProdIngestionConfigError, build_prod_app


def test_prod_factory_lists_all_missing_required_environment() -> None:
    with pytest.raises(ProdIngestionConfigError) as raised:
        build_prod_app({})

    message = str(raised.value)
    assert "FDAI_DATABASE_URL" in message
    assert "FDAI_ADLS_ACCOUNT_URL" in message
    assert "FDAI_DOCUMENT_EVENT_TOPIC" in message
    assert "FDAI_EMBEDDING_DEPLOYMENT" in message
