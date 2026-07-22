# Development Operations Gateway

This Azure Functions project provides a development-only, authenticated gateway from the local
FDAI read API to private Azure resources. It exposes registered operations rather than arbitrary
URLs, ARM paths, commands, or query text.

## Contracts

- Read operations require the configured Contributor group or the FDAI executor principal.
- Write and execute handlers are present for contract hardening but remain disabled in upstream
  Terraform with `FDAI_DEV_GATEWAY_MUTATIONS_ENABLED=0`. They are not a shipped execution path
  until a governed direct-API adapter can provide verified dry-run, audit, stop-condition, and
  rollback evidence instead of caller-asserted strings.
- Mutation idempotency keys are claimed in a private, Microsoft Entra-authenticated Blob
  container before Azure is called. A completed duplicate reuses the recorded response, a
  conflicting payload is blocked, and storage uncertainty fails closed. Stale pending claims can
  be recovered with ETag compare-and-swap after the bounded claim timeout.
- Mutations acquire a 60-second Blob lease on the target resource before ARM submission. Different
  idempotency keys therefore cannot mutate the same VM or NSG rule concurrently.
- ARM `202 Accepted` responses remain `submitted`, and the server-issued status URL stays private
  in the operation record. The executor can poll it only through `azure.operation.status` with the
  original idempotency key.
- Resource groups and private probe endpoints come from server configuration.
- Private probe configuration rejects literal IP addresses, localhost, fragments, credentials,
  and control characters before any token is requested. Probe requests never follow redirects.
- The gateway refuses to start unless `FDAI_DEV_GATEWAY_ENABLED=1` and `FDAI_ENV=dev`.
- App Service Authentication validates Microsoft Entra tokens before the anonymous Function route
  runs. Function keys are not an authorization boundary.

## Operations

| Operation | Class | Target |
|-----------|-------|--------|
| `azure.network.nsg.read` | read | One configured development NSG |
| `azure.network.peering.read` | read | Peerings for one configured development VNet |
| `azure.private.http.probe` | read | One server-registered HTTPS private endpoint |
| `azure.network.nsg.rule.upsert` | disabled write contract | One NSG security rule |
| `azure.network.nsg.rule.delete` | disabled write contract | One NSG security rule |
| `azure.compute.vm.start` | disabled execute contract | One VM |
| `azure.compute.vm.deallocate` | disabled execute contract | One VM |
| `azure.operation.status` | disabled execute status | One previously submitted mutation |

## Testing

Run the gateway contract tests from the repository root:

```sh
uv run pytest -q --no-cov tests/delivery/dev_operations_gateway
```
