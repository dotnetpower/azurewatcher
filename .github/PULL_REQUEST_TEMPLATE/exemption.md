# Exemption Request

<!--
Fill this template out for every PR that touches `rule-catalog/exemptions/`.
See `docs/runbooks/exemption-workflow.md` for the full workflow.
-->

## Scope

- **Rule id (`rule_id`)**:
- **Subscription (`scope.subscription_id`)**:
- **Resource group (`scope.resource_group`)** (optional; narrower is better):
- **Resource ref (`scope.resource_ref`)** (optional; single-resource is best):

## Justification

<!--
Minimum 20 characters. Explain what is broken, why an exemption is safer
than fixing the rule, and what the plan to remove the exemption is. Avoid
"lgtm" / "ok" / restatement of the rule id.
-->

## Time-boxing

- **Expires at (`expires_at`, RFC 3339 UTC)**:
- **Plan to remove the exemption before expiry**:

## Identities

- **Requested-By (`requested_by`, Entra OID)**:
- **Approved-By (`approved_by`, Entra OID)**:

> `Requested-By` MUST differ from `Approved-By`. Repo branch-protection
> refuses self-approvals; the CI schema check refuses the artifact.

## Safety checklist

- [ ] Exemption artifact validates via CI (`exemption-check` job).
- [ ] Justification explains the *risk* introduced, not just the request.
- [ ] Rollback: the underlying rule assignment re-applies automatically
      the moment `expires_at` passes.
- [ ] I confirm this exemption carries no customer-identifying values in
      its body (Entra OIDs are the exception and are UUIDs).
