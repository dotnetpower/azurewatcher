# Convenience targets for the local dev stack (pgvector + Redpanda).
# Real deployment lives under `infra/` (Terraform); see the roadmap.

.PHONY: dev-up dev-down dev-logs dev-nuke help

help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev-up: ## start pgvector + Redpanda locally (waits for healthchecks)
	@scripts/dev-up.sh

dev-down: ## stop the local stack (volumes preserved)
	@scripts/dev-down.sh

dev-logs: ## tail postgres + redpanda logs (optional: SERVICE=postgres)
	@scripts/dev-logs.sh $(SERVICE)

dev-nuke: ## stop the stack AND drop its volumes (fresh state next `dev-up`)
	@docker compose -f infra/local/docker-compose.yml down -v
