"""Static contracts for the private Azure OpenAI Terraform module."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MAIN = REPO_ROOT / "infra" / "modules" / "llm" / "azure-openai" / "main.tf"


def test_account_enforces_private_access_and_preserves_policy_acls() -> None:
    module = MODULE_MAIN.read_text(encoding="utf-8")

    assert "public_network_access_enabled = false" in module
    assert "local_auth_enabled            = false" in module
    assert "ignore_changes = [network_acls]" in module
