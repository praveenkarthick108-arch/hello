import datetime
from sqlalchemy import JSON, DateTime, String, Integer, select
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.config import settings


class Base(DeclarativeBase):
    pass


class TripRecord(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    # "in_progress" | "completed" | "partial" | "failed"

    trip_preferences: Mapped[dict] = mapped_column(JSON, nullable=True)
    budget_summary: Mapped[dict] = mapped_column(JSON, nullable=True)
    itinerary: Mapped[dict] = mapped_column(JSON, nullable=True)
    review_status: Mapped[dict] = mapped_column(JSON, nullable=True)
    pdf_path: Mapped[str] = mapped_column(String(512), nullable=True)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    current_phase: Mapped[str] = mapped_column(String(64), nullable=True)


_engine = create_async_engine(settings.sqlite_url, echo=settings.debug)
SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_trip_record(session_id: str, user_id: str, raw_input: str) -> None:
    async with SessionLocal() as db:
        record = TripRecord(
            session_id=session_id,
            user_id=user_id,
            status="in_progress",
            trip_preferences={"raw_input": raw_input},
            errors=[],
        )
        db.add(record)
        await db.commit()


async def update_trip_record(session_id: str, **fields) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(TripRecord).where(TripRecord.session_id == session_id)
        )
        record = result.scalar_one_or_none()
        if record:
            for key, value in fields.items():
                setattr(record, key, value)
            await db.commit()


async def get_trip_record(session_id: str) -> TripRecord | None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(TripRecord).where(TripRecord.session_id == session_id)
        )
        return result.scalar_one_or_none()


async def get_user_trips(user_id: str, limit: int = 10, offset: int = 0) -> list[TripRecord]:
    async with SessionLocal() as db:
        result = await db.execute(
            select(TripRecord)
            .where(TripRecord.user_id == user_id)
            .order_by(TripRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
