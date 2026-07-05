output "namespace_id" {
  description = "Event Hubs namespace resource id."
  value       = azurerm_eventhub_namespace.primary.id
}

output "namespace_name" {
  description = "Namespace name."
  value       = azurerm_eventhub_namespace.primary.name
}

output "kafka_bootstrap" {
  description = "Kafka bootstrap host:port."
  value       = "${azurerm_eventhub_namespace.primary.name}.servicebus.windows.net:9093"
}

output "topics" {
  description = "Provisioned topic names."
  value       = [for h in azurerm_eventhub.topic : h.name]
}

output "dlq_topics" {
  description = "Provisioned DLQ sibling names."
  value       = [for h in azurerm_eventhub.dlq : h.name]
}

