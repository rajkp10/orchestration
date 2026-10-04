variable "resource_id" {
  description = "Unique id of this Postgres instance. Names the container and its volume."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,39}$", var.resource_id))
    error_message = "resource_id must be 1-40 characters of lowercase letters, digits and hyphens."
  }
}

variable "postgres_version" {
  description = "Postgres image tag, e.g. 16.3. A patch changes only this."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+$", var.postgres_version))
    error_message = "postgres_version must look like MAJOR.MINOR, e.g. 16.3."
  }
}

variable "host_port" {
  description = "Port on localhost to publish Postgres on. Null lets Docker choose a free one."
  type        = number
  default     = null
}

variable "env" {
  description = "Environment label recorded on the container."
  type        = string
  default     = "dev"
}
