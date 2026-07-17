# APIM AI gateway module

This optional module attaches one FDAI model capability to an existing Azure API Management
instance. It does not create an APIM service, change the minimum deployment inventory, or run a
local model.

## Behavior

- Validates the FDAI caller's Entra token and configured audience.
- Uses the APIM managed identity to authenticate to both Azure OpenAI backends.
- Sends the first request to a PTU deployment.
- Retries exactly once against a same-family Standard deployment after HTTP 429.
- Removes the OpenAI-v1 `model` field and translates `/v1/chat/completions` to the Azure OpenAI
  deployment path.
- Returns mandatory `x-fdai-model-backend`, `x-fdai-capacity-unit`, and
  `x-fdai-spillover` evidence headers.

The FDAI runtime rejects APIM T2 responses without those headers. It persists the selected backend
and spillover decision through the model-health transition sink.

## Inputs

Supply the existing APIM resource group, service name, gateway origin, frontend tenant and audience,
APIM managed-identity object id, and two Azure OpenAI deployment base URLs. Each backend URL ends at
`/openai/deployments/<deployment>` and contains no query string.

The APIM managed identity receives `Cognitive Services OpenAI User` on both backend resource ids.
Policy editors therefore hold an indirect path to those identities and should remain a tightly
reviewed owner group.

## Validation

Run from the repository root:

```bash
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
```

Deployment remains part of the protected remote plan/apply workflow. Do not run `terraform apply`
from a laptop.
