"""
AWS Secrets Manager client.

Em produção (APP_ENV=production), o app busca as configurações sensíveis
do Secrets Manager no startup. Em desenvolvimento, usa o .env normalmente.

Estrutura esperada do secret (JSON):
  {
    "database_url":      "postgresql+asyncpg://user:pass@host:5432/db",
    "database_url_sync": "postgresql://user:pass@host:5432/db"
  }

O nome do secret é controlado pela env var AWS_SECRET_NAME.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def get_secret(secret_name: str, region: str = "us-east-1") -> dict:
    """
    Fetch and parse a JSON secret from AWS Secrets Manager.

    Returns an empty dict (and logs a warning) on failure so the app
    can fall back to environment variables rather than crashing.
    """
    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        secret_str = response.get("SecretString", "{}")
        return json.loads(secret_str)
    except ClientError as exc:
        logger.error("Failed to fetch secret '%s': %s", secret_name, exc)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Secret '%s' is not valid JSON: %s", secret_name, exc)
        return {}


def load_secrets_into_env(secret_name: str, region: str = "us-east-1") -> None:
    """
    Fetch a secret and inject each key as an environment variable.
    Only sets variables that are not already defined (env var takes precedence).
    Called once at application startup before Settings() is instantiated.
    """
    if not secret_name:
        return

    logger.info("Loading secrets from Secrets Manager: %s", secret_name)
    secrets = get_secret(secret_name, region)

    for key, value in secrets.items():
        env_key = key.upper()
        if env_key not in os.environ:
            os.environ[env_key] = str(value)
            logger.debug("Injected secret key: %s", env_key)

    logger.info("Loaded %d keys from Secrets Manager", len(secrets))
