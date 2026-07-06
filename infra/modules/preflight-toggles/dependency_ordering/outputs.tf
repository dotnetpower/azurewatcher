output "effective_mode" {
  description = "The mode the toggle resolved to ('strict' or 'best_effort')."
  value       = var.mode
}

output "strict_mode" {
  description = <<-EOT
    Boolean the consumer stack branches on when deciding whether to
    drive `terraform apply -target=...` per stage vs one shot.
  EOT
  value       = local.strict_mode
}

output "stages" {
  description = <<-EOT
    Ordered list of prerequisite stages the consumer serialises when
    `strict_mode == true`. In `best_effort` mode this collapses to a
    single `["all"]` element so a downstream `for_each` still works.
  EOT
  value       = local.applied_stages
}

output "canonical_stages" {
  description = <<-EOT
    The upstream canonical stage list (`[disk, nsg, private_endpoint,
    compute]` when `custom_stages` is empty). Emitted regardless of
    mode so a caller can compare against the effective list.
  EOT
  value       = local.effective_stages
}
