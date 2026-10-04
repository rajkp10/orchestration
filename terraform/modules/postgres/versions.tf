terraform {
  required_version = ">= 1.6"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# No host is set here: the provider reads DOCKER_HOST, which the orchestrator sets on
# Windows (named pipe) and leaves to the default unix socket elsewhere.
provider "docker" {}
