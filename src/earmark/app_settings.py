import base64
import hashlib
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.config import settings
from earmark.models import AppSetting
from earmark.schemas import SettingRead

logger = logging.getLogger(__name__)

SETTING_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "audiobookshelf_url",
        "label": "Audiobookshelf URL",
        "description": "URL of your Audiobookshelf server (e.g. http://localhost:13378)",
        "value_type": "string",
        "is_secret": False,
        "env_default_fn": lambda: settings.audiobookshelf_url,
    },
    {
        "key": "audiobookshelf_api_key",
        "label": "Audiobookshelf API Key",
        "description": "API key for your Audiobookshelf account",
        "value_type": "password",
        "is_secret": True,
        "env_default_fn": lambda: settings.audiobookshelf_api_key,
    },
    {
        "key": "cwa_url",
        "label": "Calibre Web URL",
        "description": "URL of your Calibre Web (OPDS) server (e.g. http://calibre.local:8083)",
        "value_type": "string",
        "is_secret": False,
        "env_default_fn": lambda: settings.cwa_url,
    },
    {
        "key": "cwa_username",
        "label": "Calibre Web Username",
        "description": "Username for Calibre Web authentication",
        "value_type": "string",
        "is_secret": True,
        "env_default_fn": lambda: settings.cwa_username,
    },
    {
        "key": "cwa_password",
        "label": "Calibre Web Password",
        "description": "Password for Calibre Web authentication",
        "value_type": "password",
        "is_secret": True,
        "env_default_fn": lambda: settings.cwa_password,
    },
    {
        "key": "timezone",
        "label": "Timezone",
        "description": "IANA timezone for displaying timestamps in the UI (e.g. America/New_York)",
        "value_type": "timezone",
        "is_secret": False,
        "env_default_fn": lambda: settings.timezone,
    },
    {
        "key": "sync_interval_seconds",
        "label": "Sync Interval (seconds)",
        "description": "How often to sync progress between Audiobookshelf and KOSync",
        "value_type": "int",
        "is_secret": False,
        "env_default_fn": lambda: str(settings.sync_interval_seconds),
    },
    {
        "key": "sync_abs_idle_seconds",
        "label": "ABS Idle Threshold (seconds)",
        "description": "Seconds Audiobookshelf must be idle before writing progress to KOSync",
        "value_type": "int",
        "is_secret": False,
        "env_default_fn": lambda: str(settings.sync_abs_idle_seconds),
    },
    {
        "key": "log_rotation_strategy",
        "label": "Log Rotation Strategy",
        "description": "How log files rotate: 'size' (by file size) or 'time' (on a schedule)",
        "value_type": "string",
        "is_secret": False,
        "env_default_fn": lambda: settings.log_rotation_strategy,
    },
    {
        "key": "log_max_size_mb",
        "label": "Log Max Size (MB)",
        "description": "Size strategy: rotate the log file once it exceeds this many megabytes",
        "value_type": "int",
        "is_secret": False,
        "env_default_fn": lambda: str(settings.log_max_size_mb),
    },
    {
        "key": "log_rotation_when",
        "label": "Log Rotation Interval",
        "description": "Time strategy: when to rotate, e.g. 'midnight', 'H' (hourly), 'D' (daily)",
        "value_type": "string",
        "is_secret": False,
        "env_default_fn": lambda: settings.log_rotation_when,
    },
    {
        "key": "log_backup_count",
        "label": "Log Files To Keep",
        "description": "How many rotated log files to keep before deleting the oldest",
        "value_type": "int",
        "is_secret": False,
        "env_default_fn": lambda: str(settings.log_backup_count),
    },
]

_DEFINITIONS_BY_KEY: dict[str, dict[str, Any]] = {d["key"]: d for d in SETTING_DEFINITIONS}


def _derive_fernet_key() -> bytes:
    raw = hashlib.sha256(settings.secret_key.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt_secret(value: str) -> str:
    return Fernet(_derive_fernet_key()).encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return Fernet(_derive_fernet_key()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ValueError(f"Failed to decrypt setting: {exc}") from exc


async def seed_settings(session: AsyncSession) -> None:
    existing_result = await session.execute(select(AppSetting))
    existing_by_key = {row.key: row for row in existing_result.scalars()}
    for defn in SETTING_DEFINITIONS:
        row = existing_by_key.get(defn["key"])
        if row is None:
            session.add(AppSetting(
                key=defn["key"],
                label=defn["label"],
                description=defn["description"],
                value_type=defn["value_type"],
                is_secret=defn["is_secret"],
                value=None,
            ))
        else:
            # Keep definition metadata in sync on existing rows (value is untouched).
            row.label = defn["label"]
            row.description = defn["description"]
            row.value_type = defn["value_type"]
            row.is_secret = defn["is_secret"]
    await session.commit()


def _get_definition(key: str) -> dict[str, Any] | None:
    return _DEFINITIONS_BY_KEY.get(key)


async def get_effective_str(key: str, default: str, session: AsyncSession) -> str:
    row = await session.get(AppSetting, key)
    if row is not None and row.value:
        if row.is_secret:
            try:
                return decrypt_secret(row.value)
            except ValueError:
                logger.warning("Could not decrypt setting %s; using default", key)
                return default
        return row.value
    return default


async def get_effective_int(key: str, default: int, session: AsyncSession) -> int:
    raw = await get_effective_str(key, str(default), session)
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def build_setting_read(row: AppSetting, defn: dict[str, Any]) -> SettingRead:
    has_db_value = bool(row.value)
    if row.is_secret:
        display_value = "••••••••" if has_db_value else ""
    elif has_db_value:
        display_value = row.value or ""
    else:
        display_value = defn["env_default_fn"]()
    return SettingRead(
        key=row.key,
        label=row.label,
        description=row.description,
        value_type=row.value_type,
        is_secret=row.is_secret,
        has_db_value=has_db_value,
        display_value=display_value,
    )
