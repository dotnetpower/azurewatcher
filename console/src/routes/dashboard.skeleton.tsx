import { t } from "../i18n";

export function DashboardSkeleton() {
  return (
    <div class="overview-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span class="sr-only">{t("shared.loadingResource", { resource: "overview" })}</span>
      <div class="overview-skeleton-content" aria-hidden="true">
        <div class="overview-skeleton-posture">
          <span class="skeleton-shimmer overview-skeleton-kicker" />
          <span class="skeleton-shimmer overview-skeleton-heading" />
          <span class="skeleton-shimmer overview-skeleton-copy" />
          <div class="overview-skeleton-meta">
            {Array.from({ length: 6 }, (_, index) => (
              <span key={index} class="skeleton-shimmer" />
            ))}
          </div>
        </div>
        <SkeletonSection layout="metrics" blocks={5} />
        <SkeletonSection layout="distributions" blocks={2} />
        <SkeletonSection layout="attention" blocks={3} />
        <SkeletonSection layout="verticals" blocks={3} />
      </div>
    </div>
  );
}

function SkeletonSection({
  layout,
  blocks,
}: {
  readonly layout: "metrics" | "distributions" | "attention" | "verticals";
  readonly blocks: number;
}) {
  return (
    <section class="overview-skeleton-section">
      <div class="overview-skeleton-section-head">
        <span class="skeleton-shimmer overview-skeleton-number" />
        <span>
          <span class="skeleton-shimmer overview-skeleton-section-heading" />
          <span class="skeleton-shimmer overview-skeleton-section-copy" />
        </span>
      </div>
      <div class={`overview-skeleton-grid is-${layout}`}>
        {Array.from({ length: blocks }, (_, index) => (
          <span key={index} class="skeleton-shimmer overview-skeleton-card" />
        ))}
      </div>
    </section>
  );
}
