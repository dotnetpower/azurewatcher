import { describe, expect, it } from "vitest";
import { IngestionApiError } from "../ingestion-api";
import { t } from "../i18n";
import { claimUploadBatch, documentCapabilityFailure } from "./document-ingestion";
import { buildDocumentViewSnapshot } from "./document-ingestion.view";

describe("Documents ViewSnapshot", () => {
  it("allows only one upload batch to own the route lock", () => {
    const lock = { current: false };
    expect(claimUploadBatch(lock)).toBe(true);
    expect(claimUploadBatch(lock)).toBe(false);
  });

  it("classifies unwired capability endpoints without hiding operational failures", () => {
    expect(documentCapabilityFailure(new IngestionApiError(404, "Not Found")))
      .toBe(t("documents.unavailable"));
    expect(documentCapabilityFailure(new IngestionApiError(501, "Not Implemented")))
      .toBe(t("documents.unavailable"));
    expect(documentCapabilityFailure(new IngestionApiError(503, "gateway unavailable")))
      .toBe("gateway unavailable");
  });

  it("publishes visible sections, controls, constraints, and current state", () => {
    const snapshot = buildDocumentViewSnapshot({
      routeLabel: "Documents",
      collection: "shared-knowledge",
      purpose: "knowledge_base",
      storageMode: "managed_copy",
      consent: false,
      uploads: [],
      capabilities: {
        supportedFormats: ["text", "ooxml", "pdf-detect-only"],
        maxFileSize: 25 * 1024 * 1024,
        maxBatchCount: 10,
        storageModes: ["managed_copy", "linked_source"],
      },
      capabilitiesAvailable: true,
      capturedAt: "2026-07-16T00:00:00Z",
    });

    expect(snapshot.purpose).toContain("shared visibility");
    expect(snapshot.glossary?.map((entry) => entry.term)).toEqual([
      "document collection",
      "processing purpose",
      "source storage mode",
      "ingestion safety checks",
    ]);
    expect(snapshot.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "supported_formats", label: "Supported formats", value: "text, ooxml, pdf-detect-only" }),
      expect.objectContaining({ key: "shared_visibility_confirmed", label: "Shared visibility confirmed", value: false }),
      expect.objectContaining({ key: "max_batch_count", value: 10 }),
    ]));
    expect(snapshot.records?.sections).toHaveLength(3);
    expect(snapshot.records?.controls).toEqual(expect.arrayContaining([
      expect.objectContaining({ control: "choose_files", label: "Choose files", enabled: true }),
      expect.objectContaining({
        control: "upload_files",
        label: "Upload files",
        enabled: false,
        disabled_reason: "Confirm shared visibility before uploading.",
      }),
    ]));
    expect(snapshot.records?.constraints?.[0]).toMatchObject({
      supported_formats: "text, ooxml, pdf-detect-only",
      max_batch_count: 10,
      files_unavailable_until_safety_checks_complete: true,
    });
  });

  it("publishes upload status and enables upload only after confirmation", () => {
    const snapshot = buildDocumentViewSnapshot({
      routeLabel: "Documents",
      collection: "shared-knowledge",
      purpose: "handover_bootstrap",
      storageMode: "managed_copy",
      consent: true,
      uploads: [
        { name: "guide.docx", size: 1024, state: "queued" },
        { name: "ready.txt", size: 256, state: "ready", uploadId: "upload-1" },
      ],
      capabilities: {
        supportedFormats: ["text", "ooxml"],
        maxFileSize: 4096,
        maxBatchCount: 2,
        storageModes: ["managed_copy"],
      },
      capabilitiesAvailable: true,
      capturedAt: "2026-07-16T00:00:00Z",
    });

    expect(snapshot.headline).toBe("2 files, 1 ready, 0 failed");
    expect(snapshot.records?.uploads).toHaveLength(2);
    expect(snapshot.records?.controls).toEqual(expect.arrayContaining([
      expect.objectContaining({
        control: "upload_files",
        label: "Upload files",
        enabled: true,
        disabled_reason: null,
      }),
    ]));
  });
});
