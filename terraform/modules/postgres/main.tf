locals {
  name = "pg-${var.resource_id}"
}

resource "random_password" "postgres" {
  length = 32
  # Alphanumeric only: the value travels through an environment variable and a
  # connection string, where punctuation invites quoting bugs.
  special = false
}

resource "docker_image" "postgres" {
  name = "postgres:${var.postgres_version}"
  # Instances share images, so destroying one must not remove the image from another.
  keep_locally = true
}

# Data lives on a named volume, so replacing the container for a patch keeps it.
resource "docker_volume" "data" {
  name = "${local.name}-data"

  # Every other attribute forces replacement, and replacing this volume deletes the
  # database. Docker also hands back an existing volume of the same name, whose labels
  # or driver may differ from what is declared here. Ignoring that drift means an apply
  # (a patch) can never replace the volume; only destroy removes it.
  lifecycle {
    ignore_changes = [labels, driver, driver_opts]
  }
}

resource "docker_container" "postgres" {
  name  = local.name
  image = docker_image.postgres.image_id

  env = [
    "POSTGRES_PASSWORD=${random_password.postgres.result}",
  ]

  volumes {
    volume_name    = docker_volume.data.name
    container_path = "/var/lib/postgresql/data"
  }

  # With no host_port, Docker picks a free port, so two instances never clash. The
  # orchestrator then passes that port back in on later applies, so the container that
  # replaces this one during a patch keeps the same address.
  ports {
    internal = 5432
    external = var.host_port
  }

  labels {
    label = "orchestrator.env"
    value = var.env
  }

  healthcheck {
    # Over TCP on purpose: during first-time initialisation the image runs a temporary
    # server that only listens on the unix socket.
    test         = ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U postgres"]
    interval     = "2s"
    timeout      = "3s"
    retries      = 15
    start_period = "5s"
  }

  # Apply returns only once the healthcheck passes, so "apply succeeded" means
  # "Postgres accepts connections".
  wait         = true
  wait_timeout = 120
}
