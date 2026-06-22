from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import datetime
from database import Base

class Sieve(Base):
    __tablename__ = "sieves"

    id = Column(Integer, primary_key=True, index=True)
    sieve_id_tag = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    nominal_size_um = Column(Float, nullable=False)
    state = Column(String, default="new")  # "new" or "used"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    runs = relationship("CalibrationRun", back_populates="sieve", cascade="all, delete-orphan")

class CalibrationFactor(Base):
    __tablename__ = "calibration_factors"

    id = Column(Integer, primary_key=True, index=True)
    pixels_per_mm = Column(Float, nullable=False)
    known_distance = Column(Float, nullable=False)
    pixel_distance = Column(Float, nullable=False)
    reference_image_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    runs = relationship("CalibrationRun", back_populates="calibration_factor")

class CalibrationRun(Base):
    __tablename__ = "calibration_runs"

    id = Column(Integer, primary_key=True, index=True)
    sieve_id = Column(Integer, ForeignKey("sieves.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    calibration_factor_id = Column(Integer, ForeignKey("calibration_factors.id"), nullable=False)
    number_of_points = Column(Integer, nullable=False)
    area_average = Column(Float, nullable=False)
    area_min = Column(Float, nullable=False)
    area_max = Column(Float, nullable=False)
    area_std = Column(Float, nullable=False)
    wire_thickness = Column(Float, nullable=False)
    processing_time = Column(Float, nullable=False)
    status = Column(String, nullable=False)  # "Pass" or "Fail"
    image_paths = Column(String, nullable=False)  # Comma-separated or JSON list of paths

    sieve = relationship("Sieve", back_populates="runs")
    calibration_factor = relationship("CalibrationFactor", back_populates="runs")
