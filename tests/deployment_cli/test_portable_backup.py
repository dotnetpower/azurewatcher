"""Portable deployment metadata backup and restore tests."""

from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.portable_backup import (
    PortableBackupError,
    create_portable_backup,
    restore_portable_backup,
)


def _write_sources(
    root: Path,
    *,
    memory_body: str = "Prefer concise incident summaries.",
) -> dict[str, Path]:
    root.mkdir()
    paths = {
        "config": root / "environment.json",
        "references": root / "references.json",
        "audit": root / "audit.json",
        "context": root / "context.json",
    }
    paths["config"].write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.environment.v1",
                "environment": "dev",
                "azure": {
                    "subscription_id": "00000000-0000-0000-0000-000000000001",
                    "tenant_id": "00000000-0000-0000-0000-000000000002",
                    "region": "koreacentral",
                },
                "execution_target": "remote-runner",
                "autonomy_mode_default": "shadow",
            }
        ),
        encoding="utf-8",
    )
    paths["references"].write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.portable-references.v1",
                "records": [
                    {"kind": "secret", "name": "chat-signing", "ref": "vault/chat-signing"},
                    {"kind": "document", "name": "runbook", "ref": "doc:runbook-001"},
                ],
            }
        ),
        encoding="utf-8",
    )
    paths["audit"].write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.portable-audit-metadata.v1",
                "source_schema": "fdai.audit.v1",
                "last_sequence": 7,
                "record_count": 7,
                "head_entry_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    paths["context"].write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.portable-user-context.v1",
                "preferences": [
                    {
                        "principal_ref": "principal:operator-001",
                        "locale": "ko",
                        "verbosity": "concise",
                        "answer_detail": "deep",
                        "answer_format": "table",
                        "answer_preferences_enabled": True,
                        "answer_intent_detail": {"comparison": "brief"},
                        "answer_intent_format": {"comparison": "bullets"},
                        "timezone": "Asia/Seoul",
                        "share_with_learner": False,
                        "revision": 3,
                        "updated_at": "2026-07-17T00:00:00Z",
                    }
                ],
                "memories": [
                    {
                        "principal_ref": "principal:operator-001",
                        "memory_id": "memory-001",
                        "category": "preference",
                        "body": memory_body,
                        "source_ref": "audit:event-001",
                        "consented_at": "2026-07-17T00:00:00Z",
                        "created_at": "2026-07-17T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return paths


def _create(paths: dict[str, Path], archive: Path):
    return create_portable_backup(
        config_path=paths["config"],
        references_path=paths["references"],
        audit_metadata_path=paths["audit"],
        user_context_path=paths["context"],
        archive_path=archive,
    )


def test_backup_round_trip_is_deterministic_private_and_allowlisted(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path / "source")
    first = tmp_path / "first.fdai-backup"
    second = tmp_path / "second.fdai-backup"

    created = _create(paths, first)
    _create(paths, second)
    restored = restore_portable_backup(
        archive_path=first,
        destination=tmp_path / "restored",
    )

    assert first.read_bytes() == second.read_bytes()
    assert created.archive_digest == restored.archive_digest
    assert created.file_count == 4
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "restored").stat().st_mode) == 0o700
    restored_names = {path.name for path in (tmp_path / "restored").iterdir()}
    assert restored_names == {
        "configuration.json",
        "references.json",
        "audit-metadata.json",
        "user-context.json",
    }
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in (tmp_path / "restored").iterdir()
    )
    archive_text = first.read_bytes().lower()
    assert b"terraform.tfstate" not in archive_text
    assert b"secret-value" not in archive_text


@pytest.mark.parametrize(
    "memory_body",
    (
        "client_secret=plain-value",
        '{"terraform_version":"1.9.0","lineage":"x","resources":[]}',
    ),
)
def test_backup_rejects_secret_values_and_terraform_state(tmp_path: Path, memory_body: str) -> None:
    paths = _write_sources(tmp_path / "source", memory_body=memory_body)
    archive = tmp_path / "blocked.fdai-backup"

    with pytest.raises(PortableBackupError, match="secret-like value|Terraform state"):
        _create(paths, archive)

    assert not archive.exists()


def test_restore_rejects_unexpected_or_tampered_members(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path / "source")
    archive = tmp_path / "backup.fdai-backup"
    _create(paths, archive)
    tampered = tmp_path / "tampered.fdai-backup"
    with (
        zipfile.ZipFile(archive, "r") as source,
        zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_STORED) as destination,
    ):
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "user-context.json":
                payload = payload.replace(b"concise", b"detailed")
            destination.writestr(info, payload)

    with pytest.raises(PortableBackupError, match="digest mismatch"):
        restore_portable_backup(archive_path=tampered, destination=tmp_path / "restored")

    assert not (tmp_path / "restored").exists()


def test_restore_refuses_existing_destination_without_mutation(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path / "source")
    archive = tmp_path / "backup.fdai-backup"
    _create(paths, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")

    with pytest.raises(PortableBackupError, match="already exists"):
        restore_portable_backup(archive_path=archive, destination=destination)

    assert marker.read_text(encoding="utf-8") == "keep\n"


def test_cli_create_and_restore_emit_stable_json(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path / "source")
    archive = tmp_path / "backup.fdai-backup"
    create_output = io.StringIO()

    create_exit = main(
        [
            "backup",
            "create",
            "--config",
            str(paths["config"]),
            "--references",
            str(paths["references"]),
            "--audit-metadata",
            str(paths["audit"]),
            "--user-context",
            str(paths["context"]),
            "--archive",
            str(archive),
            "--output",
            "json",
        ],
        stdout=create_output,
    )
    restore_output = io.StringIO()
    restore_exit = main(
        [
            "backup",
            "restore",
            "--archive",
            str(archive),
            "--destination",
            str(tmp_path / "restored"),
            "--output",
            "json",
        ],
        stdout=restore_output,
    )

    create_payload = json.loads(create_output.getvalue())
    restore_payload = json.loads(restore_output.getvalue())
    assert create_exit == restore_exit == 0
    assert create_payload["schema_version"] == ("fdai.deployment-cli.portable-backup-result.v1")
    assert create_payload["operation"] == "create"
    assert restore_payload["operation"] == "restore"
    assert create_payload["archive_digest"] == restore_payload["archive_digest"]


def test_cli_backup_failure_does_not_echo_secret_value(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path / "source", memory_body="token=do-not-print")
    output = io.StringIO()

    exit_code = main(
        [
            "backup",
            "create",
            "--config",
            str(paths["config"]),
            "--references",
            str(paths["references"]),
            "--audit-metadata",
            str(paths["audit"]),
            "--user-context",
            str(paths["context"]),
            "--archive",
            str(tmp_path / "blocked.fdai-backup"),
            "--output",
            "json",
        ],
        stdout=output,
    )

    assert exit_code == 4
    assert "do-not-print" not in output.getvalue()
