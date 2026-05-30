import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./store_intelligence.db")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class Event(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True, index=True)
    store_id = Column(String, index=True)
    camera_id = Column(String)
    visitor_id = Column(String, index=True)
    event_type = Column(String, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    zone_id = Column(String, nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float)
    metadata_ = Column("metadata", JSON)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
