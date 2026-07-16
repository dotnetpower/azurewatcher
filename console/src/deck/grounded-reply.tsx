/**
 * GroundedReply - renders a deck (assistant) turn the way the source-streaming
 * mock does: the answer text types in token by token, then a "Grounded on N
 * sources" pill summarises the reply, and expanding it rolls the cited sources
 * through a slot-machine window (reusing the retrieval-trace slot styles).
 *
 * Honest-data only: every source card is a real ``Citation`` the backend
 * returned (a fact the answer is grounded in). The pill's summary line is the
 * real reply ``source`` descriptor (``llm:<model> - <ms>`` or
 * ``deterministic``). Nothing here is fabricated - it re-presents what the
 * reply already carries.
 *
 * Single responsibility: present one grounded deck reply. No I/O, no
 * privileged calls, only self-cancelling timers.
 */

import { useState } from "preact/hooks";
import { t } from "../i18n";
import type {
  AnswerPlanMetadata,
  AnswerVerification,
  GroundedCodeArtifact,
  VerificationProgress,
} from "./backend";
import { RichContent } from "./rich-content";
import { relevantCitations, type Citation } from "./citations";

export function GroundedReply({
  turnId,
  text,
  citations,
  source,
  streaming,
  verification,
  verificationProgress,
  answerPlan,
  codeArtifacts,
  onRegenerate,
}: {
  readonly turnId: string;
  readonly text: string;
  readonly citations: readonly Citation[] | undefined;
  readonly source: string | undefined;
  /** True while the answer is still streaming tokens in from the backend. */
  readonly streaming: boolean;
  readonly verification: AnswerVerification | undefined;
  readonly verificationProgress: VerificationProgress | undefined;
  readonly answerPlan: AnswerPlanMetadata | undefined;
  readonly codeArtifacts: readonly GroundedCodeArtifact[] | undefined;
  /** Re-run the operator question that produced this reply, if known. */
  readonly onRegenerate?: () => void;
}) {
  void turnId;
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const cites = relevantCitations(citations ?? [], text);
  const evidenceReferences = cites.every((citation) =>
    citation.label.startsWith("evidence."));
  const boundedCorrection = verification?.status === "corrected" && (
    verification.reason_code === "screen_unsupported_sentences_removed" ||
    verification.reason_code === "concept_scope_claims_removed"
  );

  const copy = () => {
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      },
      () => {
        /* clipboard denied - leave the label unchanged */
      },
    );
  };

  return (
    <div class="deck-gr">
      {answerPlan ? (
        <div class="deck-answer-plan" title={t(`deck.answerPlan.format.${answerPlan.format}`)}>
          <span>Bragi</span>
          <span aria-hidden="true">·</span>
          <span>{t(`deck.answerPlan.intent.${answerPlan.intent}`)}</span>
          <span aria-hidden="true">·</span>
          <span>{t(`deck.answerPlan.detail.${answerPlan.detail_level}`)}</span>
        </div>
      ) : null}
      <div class="deck-turn-body">
        <RichContent
          text={text}
          streaming={streaming}
          suppressCode={!streaming && (codeArtifacts?.length ?? 0) > 0}
        />
      </div>

      {!streaming && codeArtifacts && codeArtifacts.length > 0 ? (
        <CodeEvidence artifacts={codeArtifacts} />
      ) : null}

      {verificationProgress && !verification ? (
        <div class="deck-verification is-active" role="status" aria-live="polite">
          <span class="deck-verification-spinner" aria-hidden="true" />
          <span>{verificationProgress.label}</span>
          {verificationProgress.total !== null && verificationProgress.completed !== null ? (
            <span class="muted">
              {verificationProgress.completed}/{verificationProgress.total}
            </span>
          ) : null}
        </div>
      ) : null}

      {verification ? (
        <div
          class={`deck-verification is-${boundedCorrection ? "verified" : verification.status}`}
          role="status"
          aria-label={`Answer ${boundedCorrection ? "verified" : verification.status}`}
        >
          <span class="deck-verification-mark" aria-hidden="true">
            {verification.status === "verified" ||
            verification.status === "consistent" ||
            boundedCorrection
              ? "\u2713"
              : verification.status === "corrected"
                ? "\u21bb"
                : "!"}
          </span>
          <span>{verificationLabel(verification)}</span>
        </div>
      ) : null}

      {verification?.semantic ? (
        <div
          class="deck-verification is-semantic-shadow"
          role="note"
          title="Experimental shadow signal; does not change the answer trust status"
        >
          <span class="deck-verification-mark" aria-hidden="true">S</span>
          <span>{semanticVerificationLabel(verification.semantic)}</span>
        </div>
      ) : null}

      {!streaming && text.trim().length > 0 ? (
        <div class="deck-gr-tools">
          <button type="button" class="deck-gr-tool" onClick={copy} title="Copy reply">
            {copied ? "Copied" : "Copy"}
          </button>
          {onRegenerate ? (
            <button
              type="button"
              class="deck-gr-tool"
              onClick={onRegenerate}
              title="Ask this question again"
            >
              Regenerate
            </button>
          ) : null}
          {source && cites.length === 0 ? (
            <span class="deck-gr-src deck-gr-src-inline muted" title="reply source">
              {source}
            </span>
          ) : null}
        </div>
      ) : null}

      {!streaming && cites.length > 0 && verification?.status !== "unverified" ? (
        <>
          <button
            type="button"
            class="deck-gr-pill"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            <span class="deck-gr-check" aria-hidden="true">
              {"\u2713"}
            </span>
            <span>
              {evidenceReferences ? "Checked against" : "Grounded on"}{" "}
              <strong>{cites.length}</strong>{" "}
              {evidenceReferences
                ? cites.length === 1
                  ? "evidence reference"
                  : "evidence references"
                : cites.length === 1
                  ? "source"
                  : "sources"}
            </span>
            {source ? <span class="deck-gr-src muted">{source}</span> : null}
            <span class="deck-gr-more">{open ? "hide sources" : "show sources"}</span>
          </button>

          {open ? (
            <ul class="deck-gr-list">
              {cites.map((c, i) => (
                <li key={`${c.label}-${i}`} class="deck-gr-item">
                  <span class="deck-gr-k">{c.label}</span>
                  {c.value !== undefined ? <span class="deck-gr-v">{c.value}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function CodeEvidence({ artifacts }: { readonly artifacts: readonly GroundedCodeArtifact[] }) {
  return (
    <details class="deck-code-evidence">
      <summary>
        <span>{t("deck.codeEvidence.label")}</span>
        <span class="muted">{t("deck.codeEvidence.count", { count: artifacts.length })}</span>
      </summary>
      <div class="deck-code-evidence-list">
        {artifacts.map((artifact, index) => (
          <section key={artifact.artifact_ref} class="deck-code-evidence-item">
            <header class="deck-code-evidence-head">
              <span class="deck-code-lang">{artifact.language}</span>
              <span class={`deck-code-validation is-${artifact.validation_status}`}>
                {t(`deck.codeEvidence.status.${artifact.validation_status}`)}
              </span>
              <span class="muted">#{index + 1}</span>
            </header>
            <RichContent
              text={`\`\`\`${artifact.language}\n${artifact.content}\`\`\``}
            />
            <footer class="deck-code-evidence-foot">
              <code>{artifact.artifact_ref}</code>
              {artifact.validation_detail ? <span>{artifact.validation_detail}</span> : null}
            </footer>
          </section>
        ))}
      </div>
    </details>
  );
}

function semanticVerificationLabel(
  semantic: NonNullable<AnswerVerification["semantic"]>,
): string {
  const latency = semantic.latency_ms > 0 ? `, ${semantic.latency_ms}ms` : "";
  switch (semantic.verdict) {
    case "entailed":
      return `Semantic shadow: supported${latency}`;
    case "contradicted":
      return `Semantic shadow: possible contradiction${latency}`;
    case "unknown":
      return `Semantic shadow: inconclusive${latency}`;
    case "unavailable":
      return "Semantic shadow: unavailable";
  }
}

export function verificationLabel(verification: AnswerVerification): string {
  const claims = verification.claims ?? [];
  const supportedClaims = claims.filter((claim) => claim.status === "supported").length;
  const claimSummary = claims.length > 0
    ? ` (${supportedClaims}/${claims.length} claims supported)`
    : "";
  const supportedSummary = supportedClaims > 0
    ? ` (${supportedClaims} ${supportedClaims === 1 ? "claim" : "claims"} supported)`
    : "";
  switch (verification.status) {
    case "verified":
      return `Verified against ${verification.evidence_refs.length} evidence reference(s)${claimSummary}`;
    case "corrected":
      if (
        verification.reason_code === "screen_unsupported_sentences_removed" ||
        verification.reason_code === "concept_scope_claims_removed"
      ) {
        return `Verified after removing unsupported statements${supportedSummary}`;
      }
      return `Corrected after evidence verification${claimSummary}`;
    case "consistent":
      const evidenceScope = verification.authority === "client_snapshot"
        ? "the current screen"
        : verification.authority === "server_read_model"
          ? "server evidence"
          : "grounded evidence";
      return claims.length > 0
        ? `Consistent with ${evidenceScope}${claimSummary}`
        : `Consistent with ${evidenceScope} (no structured claims)`;
    case "unverified":
      return `Verification could not be completed${claimSummary}`;
  }
}
