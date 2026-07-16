# Document Ingestion Gateway

This module runs the production document-ingestion ASGI gateway and a ClamAV sidecar in one Azure
Container Apps replica. The gateway streams uploads to private ADLS Gen2, persists metadata and
vectors in PostgreSQL, and authenticates every Azure data-plane call with its user-assigned Managed
Identity.

The gateway has external HTTPS ingress so the Static Web App can upload content. Source bytes are
relayed as a bounded stream and are never buffered as one in-memory request body. ClamAV is exposed
only on replica-local port `3310`.
