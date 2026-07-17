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

output "topic_ids" {
  description = "Map of primary topic name to Event Hub resource id."
  value       = { for name, hub in azurerm_eventhub.topic : name => hub.id }
}

output "dlq_topics" {
  description = "Provisioned DLQ sibling names."
  value       = [for h in azurerm_eventhub.dlq : h.name]
}

output "dlq_topic_ids" {
  description = "Map of DLQ topic name to Event Hub resource id."
  value       = { for name, hub in azurerm_eventhub.dlq : "${name}.dlq" => hub.id }
}

output "auxiliary_topic_ids" {
  description = "Map of auxiliary topic name to Event Hub resource id."
  value       = { for name, hub in azurerm_eventhub.auxiliary : name => hub.id }
}

output "all_topic_ids" {
  description = "Map of every provisioned Event Hub entity name to resource id."
  value = merge(
    { for name, hub in azurerm_eventhub.topic : name => hub.id },
    { for name, hub in azurerm_eventhub.dlq : "${name}.dlq" => hub.id },
    { for name, hub in azurerm_eventhub.auxiliary : name => hub.id },
  )
}
