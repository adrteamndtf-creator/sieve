import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from database import get_db
from models.database_models import CalibrationFactor
from models.schemas import CalibrationFactorResponse
from processing.scale_calibration import calculate_pixels_per_mm

router = APIRouter(prefix="/api/calibration", tags=["Scale Calibration"])

UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/calibrate-scale", response_model=CalibrationFactorResponse)
async def calibrate_scale(
    known_distance: float = Form(...),
    x1: float = Form(...),
    y1: float = Form(...),
    x2: float = Form(...),
    y2: float = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # 1. Compute pixel distance and scale factor
        pixels_per_mm, pixel_distance = calculate_pixels_per_mm(x1, y1, x2, y2, known_distance)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2. Save the uploaded reference image
    filename = f"scale_{file.filename}"
    # Replace spaces or weird characters
    filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 3. Save to database
    db_factor = CalibrationFactor(
        pixels_per_mm=pixels_per_mm,
        known_distance=known_distance,
        pixel_distance=pixel_distance,
        reference_image_path=file_path
    )
    db.add(db_factor)
    db.commit()
    db.refresh(db_factor)

    return db_factor

@router.get("/latest", response_model=CalibrationFactorResponse)
def get_latest_calibration(db: Session = Depends(get_db)):
    db_factor = db.query(CalibrationFactor).order_by(CalibrationFactor.id.desc()).first()
    if not db_factor:
        raise HTTPException(status_code=404, detail="No calibration factors found. Please calibrate first.")
    return db_factor

@router.get("/history", response_model=list[CalibrationFactorResponse])
def get_calibration_history(db: Session = Depends(get_db)):
    return db.query(CalibrationFactor).order_by(CalibrationFactor.id.desc()).all()
