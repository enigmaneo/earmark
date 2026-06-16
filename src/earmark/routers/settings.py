import logging
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from earmark.app_settings import (
    _DEFINITIONS_BY_KEY,
    SETTING_DEFINITIONS,
    build_setting_read,
    encrypt_secret,
)
from earmark.database import get_session
from earmark.earmark_auth import get_current_earmark_user
from earmark.models import AppSetting, User
from earmark.schemas import SettingRead, SettingUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web", tags=["settings"])


@router.get("/settings", response_model=list[SettingRead])
async def list_settings(
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> list[SettingRead]:
    rows_result = await session.execute(select(AppSetting))
    rows_by_key = {row.key: row for row in rows_result.scalars()}
    result = []
    for defn in SETTING_DEFINITIONS:
        row = rows_by_key.get(defn["key"])
        if row is None:
            row = AppSetting(
                key=defn["key"],
                label=defn["label"],
                description=defn["description"],
                value_type=defn["value_type"],
                is_secret=defn["is_secret"],
                value=None,
            )
        result.append(build_setting_read(row, defn))
    return result


@router.put("/settings/{key}", response_model=SettingRead)
async def update_setting(
    key: str,
    body: SettingUpdate,
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> SettingRead:
    defn = _DEFINITIONS_BY_KEY.get(key)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Unknown setting: {key}")

    if not body.value:
        raise HTTPException(status_code=422, detail="value must be non-empty; use DELETE to clear")

    if defn["value_type"] == "int":
        try:
            parsed = int(body.value)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{key} requires an integer value")
        if parsed < 1:
            raise HTTPException(status_code=422, detail=f"{key} must be a positive integer")
    elif defn["value_type"] == "timezone":
        if body.value not in available_timezones():
            raise HTTPException(
                status_code=422, detail=f"{body.value} is not a valid IANA timezone"
            )

    stored_value = encrypt_secret(body.value) if defn["is_secret"] else body.value

    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(
            key=key,
            label=defn["label"],
            description=defn["description"],
            value_type=defn["value_type"],
            is_secret=defn["is_secret"],
        )
        session.add(row)
    row.value = stored_value
    await session.commit()
    await session.refresh(row)

    if key == "sync_interval_seconds":
        try:
            from earmark.scheduler import reschedule_sync_job
            reschedule_sync_job(int(body.value))
            logger.info("Rescheduled sync job to %s seconds", body.value)
        except Exception:
            logger.warning("Could not reschedule sync job", exc_info=True)

    if key.startswith("log_"):
        try:
            from earmark.logging_config import configure_file_logging
            await configure_file_logging(session)
        except Exception:
            logger.warning("Could not reconfigure file logging", exc_info=True)

    return build_setting_read(row, defn)


@router.delete("/settings/{key}", response_model=SettingRead)
async def clear_setting(
    key: str,
    _user: User = Depends(get_current_earmark_user),
    session: AsyncSession = Depends(get_session),
) -> SettingRead:
    defn = _DEFINITIONS_BY_KEY.get(key)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Unknown setting: {key}")

    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(
            key=key,
            label=defn["label"],
            description=defn["description"],
            value_type=defn["value_type"],
            is_secret=defn["is_secret"],
            value=None,
        )
    else:
        row.value = None
        await session.commit()
        await session.refresh(row)

    return build_setting_read(row, defn)
