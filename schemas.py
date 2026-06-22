from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# Sieve schemas
class SieveBase(BaseModel):
    sieve_id_tag: str
    name: str
    nominal_size_um: float
    state: str = "new"

class SieveCreate(SieveBase):
    pass

class SieveResponse(SieveBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Calibration Factor schemas
class CalibrationFactorBase(BaseModel):
    pixels_per_mm: float
    known_distance: float
    pixel_distance: float
    reference_image_path: Optional[str] = None

class CalibrationFactorCreate(BaseModel):
    known_distance: float
    x1: float
    y1: float
    x2: float
    y2: float

class CalibrationFactorResponse(CalibrationFactorBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Calibration Run schemas
class CalibrationRunResponse(BaseModel):
    id: int
    sieve_id: int
    sieve: SieveResponse
    timestamp: datetime
    calibration_factor_id: int
    calibration_factor: CalibrationFactorResponse
    number_of_points: int
    area_average: float
    area_min: float
    area_max: float
    area_std: float
    wire_thickness: float
    processing_time: float
    status: str
    image_paths: str

    class Config:
        from_attributes = True

# Dashboard Stats schema
class DashboardStatsResponse(BaseModel):
    total_sieves: int
    total_runs: int
    pass_rate: float
    latest_runs: List[CalibrationRunResponse]
