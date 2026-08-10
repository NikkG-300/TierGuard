variable "az" {
  default = "us-east-1a"
}

resource "aws_vpc" "vpc" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.vpc.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = var.az
}

resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.vpc.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = var.az
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.vpc.id
}

# Elastic IP allocated FOR the NAT gateway inside the module — attached via
# allocation_id below, so it should NOT be flagged as an unattached EIP.
resource "aws_eip" "nat_eip" {
}

resource "aws_nat_gateway" "nat" {
  subnet_id     = aws_subnet.public.id
  allocation_id = aws_eip.nat_eip.id
}

resource "aws_security_group" "sg" {
  name   = "allow-all"
  vpc_id = aws_vpc.vpc.id

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

output "public_subnet_ids" {
  value = [aws_subnet.public.id]
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "db_subnet_group_name" {
  value = aws_db_subnet_group.main.name
}

output "security_group_id" {
  value = aws_security_group.sg.id
}

resource "aws_db_subnet_group" "main" {
  name       = "main"
  subnet_ids = [aws_subnet.public.id, aws_subnet.private.id]
}