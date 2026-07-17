export interface MutationIntentIdentity {
  readonly fingerprint: string;
  readonly idempotencyKey: string;
}

export function identityForMutationIntent(
  current: MutationIntentIdentity | null,
  fingerprint: string,
  createKey: () => string = () => crypto.randomUUID(),
): MutationIntentIdentity {
  if (current?.fingerprint === fingerprint) return current;
  return { fingerprint, idempotencyKey: createKey() };
}
