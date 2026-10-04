# A platform with no provider at all: terraform_data is built into Terraform, so the
# pluggability test runs the real CLI without Docker or a network.

variable "resource_id" {
  type = string
}

variable "release" {
  type = string
}

resource "terraform_data" "this" {
  input = {
    resource_id = var.resource_id
    release     = var.release
  }
}

output "release" {
  value = terraform_data.this.output.release
}
