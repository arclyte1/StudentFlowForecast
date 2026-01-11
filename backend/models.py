from sqlalchemy import Column, Integer, String, DateTime, Text, Float
from sqlalchemy.sql import func
from database import Base


class StudentData(Base):
    __tablename__ = "student_data"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, index=True)
    course = Column(Integer, nullable=False)
    admission = Column(Integer, nullable=False, default=0)
    transfers_in = Column(Integer, nullable=False, default=0)
    expelled = Column(Integer, nullable=False, default=0)
    academic_leave = Column(Integer, nullable=False, default=0)
    restored = Column(Integer, nullable=False, default=0)


class ForecastData(Base):
    """Хранение прогнозов"""
    __tablename__ = "forecast_data"

    id = Column(Integer, primary_key=True, index=True)
    course = Column(Integer, nullable=False, index=True)
    process = Column(String(50), nullable=False, index=True)  # admission, transfers_in, etc.
    year = Column(Integer, nullable=False)
    yhat = Column(Float, nullable=False)
    yhat_lower = Column(Float, nullable=False)
    yhat_upper = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class ForecastMeta(Base):
    """Метаданные прогноза (для проверки актуальности)"""
    __tablename__ = "forecast_meta"

    id = Column(Integer, primary_key=True, index=True)
    data_hash = Column(String(64), nullable=False)  # hash данных на момент построения прогноза
    created_at = Column(DateTime, server_default=func.now())
    periods = Column(Integer, nullable=False, default=5)
