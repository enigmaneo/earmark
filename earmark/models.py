from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from earmark.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    kosync_users: Mapped[list["KosyncUser"]] = relationship(back_populates="user")


class KosyncUser(Base):
    __tablename__ = "kosync_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="kosync_users")
    progress: Mapped[list["ReadingProgress"]] = relationship(back_populates="kosync_user")


class ReadingProgress(Base):
    __tablename__ = "reading_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    kosync_user_id: Mapped[int] = mapped_column(ForeignKey("kosync_users.id"), index=True)
    document: Mapped[str] = mapped_column(String(500), index=True)
    progress: Mapped[str] = mapped_column(String(1000))
    percentage: Mapped[float] = mapped_column(Float)
    device: Mapped[str] = mapped_column(String(255))
    device_id: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authors: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    kosync_user: Mapped["KosyncUser"] = relationship(back_populates="progress")
