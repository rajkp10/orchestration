output "resource_id" {
  value = var.resource_id
}

output "container_name" {
  value = docker_container.postgres.name
}

output "postgres_version" {
  value = var.postgres_version
}

output "env" {
  value = var.env
}

output "host_port" {
  description = "Port on localhost that Docker mapped to the container's 5432."
  value       = docker_container.postgres.ports[0].external
}

output "password" {
  value     = random_password.postgres.result
  sensitive = true
}
