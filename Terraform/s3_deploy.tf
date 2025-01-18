terraform {
    required_providers {
        as = {
            source = "hashicorp/aws"
            version = "~> 3.0"
        }
    }
}

provider "aws" {
    region = "eu-west-3"
}

resource "aws_s3_bucket" "k8s_storage"{
    bucket = "kap-bucket"
    force_destroy = true
    tags = {
        Name = "kap-bucket"
    }

}
