terraform {
    required_providers {
        aws = {
            source = "hashicorp/aws"
            version = "~> 3.0"
        }
    }
}

variable "region" {
   type = string
}

provider "aws" {
    region = var.region
}

resource "aws_s3_bucket" "k8s_storage"{
    bucket = "kap-bucket"
    force_destroy = true
    tags = {
        Name = "kap-bucket"
    }

}
