terraform {
  required_version = ">= 1.3"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"

  # These let terraform plan run with NO AWS credentials — the fixture only
  # needs to produce plan JSON, nothing is actually created.
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}

# --- resources that fit the Free Tier (should produce NO findings) ---------

module "network" {
  source = "./modules/network"
}

resource "aws_instance" "good" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"
  tags = {
    Name = "good-t3-micro"
  }
}

resource "aws_eip" "attached" {
  instance = aws_instance.good.id
}

resource "aws_db_instance" "good_db" {
  allocated_storage     = 20
  storage_type          = "gp3"
  engine                = "mysql"
  engine_version        = "8.0"
  instance_class        = "db.t3.micro"
  username              = "admin"
  password              = "ChangeMe123!"
  skip_final_snapshot   = true
  db_subnet_group_name  = module.network.db_subnet_group_name
  vpc_security_group_ids = [module.network.security_group_id]
}

resource "aws_ebs_volume" "good_volume" {
  availability_zone = "us-east-1a"
  size              = 25
}

resource "aws_dynamodb_table" "ok_provisioned" {
  name           = "ok-provisioned"
  billing_mode   = "PROVISIONED"
  read_capacity  = 10
  write_capacity = 10
  hash_key       = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

# --- resources that WILL cost money (should produce block findings) --------

resource "aws_instance" "bad_type" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.large"
}

resource "aws_eip" "unattached" {
}

resource "aws_db_instance" "big_class" {
  allocated_storage   = 20
  engine              = "mysql"
  instance_class      = "db.m5.large"
  username            = "admin"
  password            = "ChangeMe123!"
  skip_final_snapshot = true
  db_subnet_group_name = module.network.db_subnet_group_name
  vpc_security_group_ids = [module.network.security_group_id]
}

resource "aws_db_instance" "big_storage" {
  allocated_storage    = 100
  engine               = "mysql"
  instance_class       = "db.t3.micro"
  username             = "admin"
  password             = "ChangeMe123!"
  skip_final_snapshot  = true
  db_subnet_group_name = module.network.db_subnet_group_name
  vpc_security_group_ids = [module.network.security_group_id]
}

resource "aws_lb" "app_lb" {
  name     = "app-lb"
  internal = true
  subnets  = module.network.public_subnet_ids
}

resource "aws_ebs_volume" "big_volume" {
  availability_zone = "us-east-1a"
  size              = 50
}

resource "aws_ebs_volume" "io1_volume" {
  availability_zone = "us-east-1a"
  size              = 5
  type              = "io1"
  iops              = 100
}

resource "aws_secretsmanager_secret" "my_secret" {
  name = "my-secret"
}

resource "aws_dynamodb_table" "big_provisioned" {
  name           = "big-provisioned"
  billing_mode   = "PROVISIONED"
  read_capacity  = 100
  write_capacity = 5
  hash_key       = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

# --- resources that are situational (should produce warn findings) ----------

resource "aws_dynamodb_table" "on_demand" {
  name         = "on-demand"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
}

resource "aws_lambda_function" "big_memory" {
  function_name = "big-memory"
  role          = "arn:aws:iam::123456789012:role/lambda-role"
  image_uri     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/app:latest"
  package_type  = "Image"
  memory_size   = 2048
}