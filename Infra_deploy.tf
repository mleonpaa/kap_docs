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

variable "key_name" {
   type = string
}

variable "master_instance_type"{
   type = string
}

variable "worker_instance_type"{
   type = string
}

variable "service_instance_type"{
   type = string
}

variable "num_masters"{
   type = number
}

variable "num_workers"{
   type = number
}

provider "aws" {
    region = var.region
}

#Network Environment

resource "aws_vpc" "k8s" {
    cidr_block = "10.0.0.0/16"
    enable_dns_hostnames = true
    tags = {
        Name = "k8s_vpc"
  }
}

resource "aws_internet_gateway" "k8s" {
  vpc_id = aws_vpc.k8s.id

  tags = {
    Name = "k8s_intenet_gateway"
  }
}

#Public Subnet Configuration

resource "aws_subnet" "k8s_public" {
  vpc_id     = aws_vpc.k8s.id
  cidr_block = "10.0.1.0/24"
  map_public_ip_on_launch = true

  tags = {
    Name = "k8s_pub_subnet"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.k8s.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.k8s.id
  }
  
}

resource "aws_route_table_association" "public" {
  subnet_id = aws_subnet.k8s_public.id
  route_table_id = aws_route_table.public.id
  
}

#Private Subnet Configuration

resource "aws_subnet" "k8s_private" {
  vpc_id     = aws_vpc.k8s.id
  cidr_block = "10.0.2.0/24"
  availability_zone = aws_subnet.k8s_public.availability_zone
  depends_on = [ aws_subnet.k8s_public ]

  tags = {
    Name = "k8s_priv_subnet"
  }
  
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.k8s.id

  route {
    cidr_block = "0.0.0.0/0"
    network_interface_id = aws_network_interface.nat.id
  }

}

resource "aws_route_table_association" "private" {
  subnet_id = aws_subnet.k8s_private.id
  route_table_id = aws_route_table.private.id
  
}

#Service Security Group Configuration

resource "aws_security_group" "svc_sec_group_tf" {
    name = "svc_sec_group"
    vpc_id = aws_vpc.k8s.id
}

resource "aws_security_group_rule" "svc_allow_kube_inbound" {
    type = "ingress"
    security_group_id = aws_security_group.svc_sec_group_tf.id

    from_port         = 6443
    to_port           = 6443
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "svc_allow_haproxy_dash" {

    type = "ingress"
    security_group_id = aws_security_group.svc_sec_group_tf.id

    from_port         = 8080
    to_port           = 8080
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "svc_allow_ssh_inbound" {

    type = "ingress"
    security_group_id = aws_security_group.svc_sec_group_tf.id

    from_port         = 22
    to_port           = 22
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "svc_allow_https_inbound" {

    type = "ingress"
    security_group_id = aws_security_group.svc_sec_group_tf.id

    from_port         = 443
    to_port           = 443
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "svc_allow_http_inbound" {

    type = "ingress"
    security_group_id = aws_security_group.svc_sec_group_tf.id

    from_port         = 80
    to_port           = 80
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "allow_icmp_inbound" {
    type = "ingress"
    security_group_id = aws_security_group.svc_sec_group_tf.id

    from_port         = -1
    to_port           = -1
    protocol          = "icmp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "allow_all_outbound" {
  type              = "egress"
  security_group_id = aws_security_group.svc_sec_group_tf.id

  from_port   = 0
  to_port     = 0
  protocol    = "-1"
  cidr_blocks = ["0.0.0.0/0"]

}

#Kubernetes Node's Security Group Configuration

resource "aws_security_group" "k8s_sec_group_tf" {
    name = "k8s_sec_group"
    vpc_id = aws_vpc.k8s.id
}

variable "set_ports" {
    type = map(object({
        from_port = number
        to_port = number
    }))

    default = {
        api = { from_port = 6443, to_port = 6443}
        etcd = { from_port = 2379, to_port = 2380}
        kubelet = { from_port = 10250, to_port = 10250}
        kube-scheduler = { from_port = 10259, to_port = 10259}
        kube-controller-manager = { from_port = 10257, to_port = 10257}
        kube-proxy = { from_port = 10256, to_port = 10256}
    }
  
}

resource "aws_security_group_rule" "k8s_allow_kube_inbound" {
    for_each = var.set_ports

    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = each.value.from_port
    to_port           = each.value.to_port
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "k8s_allow_cni_inbound" {
    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = 8472
    to_port           = 8472
    protocol          = "udp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "k8s_allow_loopback_inbound" {
    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = 0
    to_port           = 0
    protocol          = -1
    cidr_blocks       = ["127.0.0.0/8"]
    
}

resource "aws_security_group_rule" "k8s_allow_https_inbound" {

    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = 443
    to_port           = 443
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "k8s_allow_http_inbound" {

    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = 80
    to_port           = 80
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "k8s_allow_ssh_inbound" {
    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = 22
    to_port           = 22
    protocol          = "tcp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "k8s_allow_icmp_inbound" {
    type = "ingress"
    security_group_id = aws_security_group.k8s_sec_group_tf.id

    from_port         = -1
    to_port           = -1
    protocol          = "icmp"
    cidr_blocks       = ["0.0.0.0/0"]
    
}

resource "aws_security_group_rule" "k8s_allow_all_outbound" {
  type              = "egress"
  security_group_id = aws_security_group.k8s_sec_group_tf.id

  from_port   = 0
  to_port     = 0
  protocol    = "-1"
  cidr_blocks = ["0.0.0.0/0"]

}


#Public Network Interfaces

resource "aws_network_interface" "nat" {

    subnet_id = aws_subnet.k8s_public.id
    private_ips = ["10.0.1.100"]
    security_groups = [aws_security_group.svc_sec_group_tf.id]
    source_dest_check = false
  
}

resource "aws_network_interface" "svc" {

    subnet_id = aws_subnet.k8s_public.id
    private_ips = ["10.0.1.101"]
    security_groups = [aws_security_group.svc_sec_group_tf.id]
  
}

#Public Instances

resource "aws_instance" "NAT"{

    ami = "ami-083a66db966d63712"
    instance_type = "t2.micro"
    key_name = "test01-key"
    availability_zone = aws_subnet.k8s_public.availability_zone
    
    network_interface {
      device_index = 0
      network_interface_id = aws_network_interface.nat.id
    }
    
    tags = {
        Name = "NAT"
    }

}

resource "aws_instance" "kservice"{

    ami = "ami-07922e223d3d0ca60"
    instance_type = var.service_instance_type
    key_name = var.key_name
    availability_zone = aws_subnet.k8s_public.availability_zone
    
    network_interface {
      device_index = 0
      network_interface_id = aws_network_interface.svc.id
    }

    user_data =  <<-EOF
              #!/bin/bash
              sudo apt update -y
              sudo apt install ansible-core -y
              GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no" git clone https://github.com/mleonpaa/kap.git /home/ubuntu/kap
              sudo chown -R ubuntu:ubuntu /home/ubuntu/kap/
              EOF
    
    tags = {
        Name = "kservice"
    }

}


#Kubernetes Node's Interfaces


resource "aws_network_interface" "k8s_masters" {
    count = var.num_masters

    subnet_id = aws_subnet.k8s_private.id
    security_groups = [aws_security_group.k8s_sec_group_tf.id]
  
}

resource "aws_network_interface" "k8s_workers" {
    count = var.num_workers

    subnet_id = aws_subnet.k8s_private.id
    security_groups = [aws_security_group.k8s_sec_group_tf.id]
  
}

#Kubernetes Nodes

resource "aws_instance" "kmasters"{
    count = var.num_masters

    ami = "ami-07922e223d3d0ca60"
    instance_type = var.master_instance_type
    key_name = var.key_name
    availability_zone = aws_subnet.k8s_private.availability_zone

    network_interface {
      device_index = 0
      network_interface_id = aws_network_interface.k8s_masters[count.index].id
    }
    
    tags = {
        Name = "kmaster${count.index}"
    }

    user_data =  <<-EOF
              #!/bin/bash
              cat <<FILE_EOF > /etc/modules-load.d/containerd.conf
              overlay
              br_netfilter
              FILE_EOF
              sudo modprobe overlay
              sudo modprobe br_netfilter
              cat <<FILE_EOF > /etc/sysctl.d/99-kubernetes-cri.conf
              net.bridge.bridge-nf-call-iptables=1
              net.ipv4.ip_forward=1
              net.bridge.bridge-nf-call-ip6tables=1
              FILE_EOF
              sudo sysctl -p /etc/sysctl.d/99-kubernetes-cri.conf
              EOF
   
}

output "kmasters_info" {
    value = {
        for instance in aws_instance.kmasters : instance.tags["Name"] => instance.private_ip
    }
}


resource "aws_instance" "kworkers"{
    count = var.num_workers

    ami = "ami-07922e223d3d0ca60"
    instance_type = var.worker_instance_type
    key_name = var.key_name
    availability_zone = aws_subnet.k8s_private.availability_zone

    network_interface {
      device_index = 0
      network_interface_id = aws_network_interface.k8s_workers[count.index].id
    }
    
    tags = {
        Name = "kworker${count.index}"
    }

    user_data =  <<-EOF
              #!/bin/bash
              cat <<FILE_EOF > /etc/modules-load.d/containerd.conf
              overlay
              br_netfilter
              FILE_EOF
              sudo modprobe overlay
              sudo modprobe br_netfilter
              cat <<FILE_EOF > /etc/sysctl.d/99-kubernetes-cri.conf
              net.bridge.bridge-nf-call-iptables=1
              net.ipv4.ip_forward=1
              net.bridge.bridge-nf-call-ip6tables=1
              FILE_EOF
              sudo sysctl -p /etc/sysctl.d/99-kubernetes-cri.conf
              EOF

}

output "kworkers_info" {
    value = {
        for instance in aws_instance.kworkers : instance.tags["Name"] => instance.private_ip
    }
}
