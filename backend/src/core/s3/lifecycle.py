"""Однократная настройка lifecycle для локального export-бакета MinIO."""

import asyncio

import aioboto3
from botocore.exceptions import ClientError
from types_aiobotocore_s3.type_defs import LifecycleRuleTypeDef, LifecycleRuleUnionTypeDef

from src.config import cfg
from src.core.s3.client import S3Client


async def configure_local_export_lifecycle() -> None:
    """Синхронизирует своё правило, сохраняя чужие правила в бакете."""
    bucket = cfg.s3.bucket_exports
    prefix = f"{cfg.s3.export_prefix.rstrip('/')}/"
    days = (cfg.s3.export_retention_hours + 23) // 24
    rule_id = "local-export-expiration"
    rule: LifecycleRuleTypeDef = {
        "ID": rule_id,
        "Status": "Enabled",
        "Filter": {"Prefix": prefix},
        "Expiration": {"Days": days},
    }

    async with S3Client(aioboto3.Session()).get() as client:
        try:
            response = await client.get_bucket_lifecycle_configuration(Bucket=bucket)
            current_rules: list[LifecycleRuleUnionTypeDef] = list(response["Rules"])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchLifecycleConfiguration":
                raise
            current_rules = []

        for current in current_rules:
            current_filter = current.get("Filter") or {}
            current_prefix = current_filter.get("Prefix", current.get("Prefix"))
            if current.get("ID") != rule_id and current_prefix == prefix:
                raise RuntimeError(f"Для префикса {prefix} уже есть другое lifecycle-правило")

        desired_rules: list[LifecycleRuleUnionTypeDef] = [
            current for current in current_rules if current.get("ID") != rule_id
        ]
        desired_rules.append(rule)
        if current_rules != desired_rules:
            await client.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration={"Rules": desired_rules},
            )


if __name__ == "__main__":
    asyncio.run(configure_local_export_lifecycle())
