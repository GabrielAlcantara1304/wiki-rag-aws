# ── Bastion Host ─────────────────────────────────────────────────────────────
# Access via SSM Session Manager — no SSH key, no inbound port needed.
#
# To connect:
#   aws ssm start-session --target <instance_id> --region <region>
#
# To reach EKS after connecting:
#   aws eks update-kubeconfig --name <cluster> --region <region>
#   kubectl get nodes

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

# ── IAM role (SSM + EKS read) ─────────────────────────────────────────────
resource "aws_iam_role" "bastion" {
  name = "${var.name}-bastion"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_policy" "eks_access" {
  name        = "${var.name}-bastion-eks"
  description = "Allow bastion to describe EKS clusters and use kubectl"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EKSDescribe"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters",
          "eks:AccessKubernetesApi",
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "eks_access" {
  role       = aws_iam_role.bastion.name
  policy_arn = aws_iam_policy.eks_access.arn
}

resource "aws_iam_instance_profile" "bastion" {
  name = "${var.name}-bastion"
  role = aws_iam_role.bastion.name
}

# ── Security Group ────────────────────────────────────────────────────────────
# SSM uses HTTPS outbound — no inbound rules needed.
resource "aws_security_group" "bastion" {
  name        = "${var.name}-bastion"
  description = "Bastion — SSM access only (no inbound SSH)"
  vpc_id      = var.vpc_id

  egress {
    description = "HTTPS to AWS endpoints (SSM, ECR, etc.)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name}-bastion" })
}

# ── EC2 Instance ──────────────────────────────────────────────────────────────
resource "aws_instance" "bastion" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  subnet_id              = var.public_subnet_id
  iam_instance_profile   = aws_iam_instance_profile.bastion.name
  vpc_security_group_ids = [aws_security_group.bastion.id]

  # No public IP needed when using SSM via VPC endpoint (or NAT)
  associate_public_ip_address = true

  metadata_options {
    http_tokens = "required"  # IMDSv2
  }

  user_data = <<-USERDATA
    #!/bin/bash
    yum install -y aws-cli kubectl
    # Install kubectl
    curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
  USERDATA

  tags = merge(var.tags, { Name = "${var.name}-bastion" })
}
