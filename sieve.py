import os
import time
import json
import math
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
import io
import csv

from database import get_db
from models.database_models import Sieve, CalibrationFactor, CalibrationRun
from models.schemas import CalibrationRunResponse
from processing.otsu_preprocessing import preprocess_mesh_image
from processing.hole_measurement import measure_holes
from processing.wire_thickness import measure_wire_thickness

router = APIRouter(prefix="/api/sieve", tags=["Sieve Analysis"])

UPLOAD_DIR = "./uploads"
PREVIEW_DIR = "./uploads/previews"
RESULTS_DIR = "./uploads/results"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PREVIEW_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# ASTM E11 Tolerances for wire sieves: (nominal size in um) -> (average tolerance um, max opening limit um)
ASTM_E11_TOLERANCES = {
    20: (2.0, 35.0),
    25: (2.0, 41.0),
    32: (3.0, 50.0),
    38: (3.0, 57.0),
    45: (3.0, 66.0),
    53: (3.0, 76.0),
    63: (4.0, 89.0),
    75: (4.0, 103.0),
    90: (5.0, 122.0),
    106: (5.0, 141.0),
    125: (5.0, 163.0),
    150: (6.0, 192.0),
    180: (7.0, 227.0),
    212: (8.0, 263.0),
    250: (9.0, 306.0),
    300: (10.0, 363.0),
    355: (12.0, 425.0),
    425: (14.0, 502.0),
    500: (16.0, 585.0),
    600: (19.0, 695.0),
    710: (22.0, 815.0),
    850: (25.0, 970.0),
    1000: (30.0, 1135.0)
}

@router.post("/analyze")
async def analyze_sieve(
    sieve_id_tag: str = Form(...),
    sieve_name: str = Form(...),
    nominal_size_um: float = Form(...),
    sieve_state: str = Form("new"),
    calibration_factor_id: int = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    start_time = time.time()
    
    # 1. Fetch calibration factor
    if calibration_factor_id:
        cf = db.query(CalibrationFactor).filter(CalibrationFactor.id == calibration_factor_id).first()
        if not cf:
            raise HTTPException(status_code=400, detail="Specified calibration factor not found.")
    else:
        # Use latest calibration factor
        cf = db.query(CalibrationFactor).order_by(CalibrationFactor.id.desc()).first()
        if not cf:
            raise HTTPException(status_code=400, detail="No calibration factor available. Please perform scale calibration first.")

    pixels_per_mm = cf.pixels_per_mm

    # 2. Get or create Sieve
    sieve = db.query(Sieve).filter(Sieve.sieve_id_tag == sieve_id_tag).first()
    if not sieve:
        sieve = Sieve(
            sieve_id_tag=sieve_id_tag,
            name=sieve_name,
            nominal_size_um=nominal_size_um,
            state=sieve_state
        )
        db.add(sieve)
        db.commit()
        db.refresh(sieve)
    else:
        # Update details in case they changed
        sieve.name = sieve_name
        sieve.nominal_size_um = nominal_size_um
        sieve.state = sieve_state
        db.commit()

    # Pre-generate a unique Run ID using DB autoincrement sequence (we can use dummy commit if needed, or save later)
    # To keep things clean, we will run the pipeline and save the run at the end.
    
    # Temporarily save images and process
    all_hole_areas = []
    wire_thicknesses = []
    saved_orig_paths = []
    previews = []
    
    image_details_log = []

    for idx, upload_file in enumerate(files):
        # Save original file
        filename = f"sieve_{sieve.id}_{idx}_{upload_file.filename}"
        filename = "".join(c for c in filename if c.isalnum() or c in "._-")
        orig_path = os.path.join(UPLOAD_DIR, filename)
        
        with open(orig_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
            
        saved_orig_paths.append(orig_path)
        
        # Run preprocessing (pass sieve.id as a temp run_id indicator)
        orig_p, otsu_p, filt_p, binary_img = preprocess_mesh_image(
            image_path=orig_path,
            output_dir=PREVIEW_DIR,
            run_id=int(time.time()), # Using timestamp as temporary run id for files
            image_idx=idx,
            nominal_size_um=nominal_size_um,
            pixels_per_mm=pixels_per_mm
        )
        
        # Run Hole Measurement
        hole_res = measure_holes(binary_img, pixels_per_mm)
        
        # Run Wire Thickness
        wire_res = measure_wire_thickness(binary_img, pixels_per_mm, nominal_size_um)
        
        all_hole_areas.extend(hole_res["valid_areas"])
        wire_thicknesses.append(wire_res["wire_thickness_mm"])
        
        previews.append({
            "original": orig_p,
            "otsu": otsu_p,
            "filtered": filt_p
        })
        
        image_details_log.append({
            "filename": upload_file.filename,
            "alignment_angle": wire_res["alignment_angle"],
            "wire_thickness_mm": wire_res["wire_thickness_mm"],
            "horizontal_projection": wire_res["horizontal_projection"],
            "vertical_projection": wire_res["vertical_projection"],
            "horizontal_peaks": wire_res["horizontal_peaks"],
            "vertical_peaks": wire_res["vertical_peaks"],
            "total_holes_detected": hole_res["total_analyzed"],
            "outliers_count": hole_res["outliers_count"]
        })

    if not all_hole_areas:
        # Cleanup uploaded files and throw exception
        raise HTTPException(status_code=400, detail="Failed to detect any valid sieve holes in the uploaded images. Check quality or binarization.")

    # 3. Aggregate Stats
    avg_area = float(np_mean := sum(all_hole_areas) / len(all_hole_areas))
    min_area = float(min(all_hole_areas))
    max_area = float(max(all_hole_areas))
    
    # Calculate standard deviation
    variance = sum((x - avg_area) ** 2 for x in all_hole_areas) / len(all_hole_areas)
    std_area = float(math.sqrt(variance))
    
    avg_wire_thickness = float(sum(wire_thicknesses) / len(wire_thicknesses))
    processing_time = float(time.time() - start_time)

    # 4. Compliance Check (ASTM E11)
    # Standard deviation / average check
    avg_opening_um = math.sqrt(avg_area) * 1000.0
    max_opening_um = math.sqrt(max_area) * 1000.0
    
    status = "Pass"
    if nominal_size_um in ASTM_E11_TOLERANCES:
        tol_avg, limit_max = ASTM_E11_TOLERANCES[nominal_size_um]
        is_avg_ok = abs(avg_opening_um - nominal_size_um) <= tol_avg
        is_max_ok = max_opening_um <= limit_max
        if not (is_avg_ok and is_max_ok):
            status = "Fail"
    else:
        # Fallback tolerance check (8% on average opening, 30% on max opening)
        tol_avg = nominal_size_um * 0.08
        limit_max = nominal_size_um * 1.30
        is_avg_ok = abs(avg_opening_um - nominal_size_um) <= tol_avg
        is_max_ok = max_opening_um <= limit_max
        if not (is_avg_ok and is_max_ok):
            status = "Fail"

    # 5. Save Calibration Run DB record
    db_run = CalibrationRun(
        sieve_id=sieve.id,
        calibration_factor_id=cf.id,
        number_of_points=len(all_hole_areas),
        area_average=avg_area,
        area_min=min_area,
        area_max=max_area,
        area_std=std_area,
        wire_thickness=avg_wire_thickness,
        processing_time=processing_time,
        status=status,
        image_paths=",".join(saved_orig_paths)
    )
    db.add(db_run)
    db.commit()
    db.refresh(db_run)

    # 6. Save raw analysis detail data to a separate JSON file in RESULTS_DIR
    result_data = {
        "run_id": db_run.id,
        "valid_areas": all_hole_areas,
        "previews": previews,
        "images_details": image_details_log,
        "avg_opening_um": avg_opening_um,
        "max_opening_um": max_opening_um
    }
    
    result_json_path = os.path.join(RESULTS_DIR, f"run_{db_run.id}_data.json")
    with open(result_json_path, "w") as f:
        json.dump(result_data, f)
        
    return {
        "run_id": db_run.id,
        "status": status,
        "area_average": avg_area,
        "area_min": min_area,
        "area_max": max_area,
        "area_std": std_area,
        "wire_thickness": avg_wire_thickness,
        "number_of_points": len(all_hole_areas),
        "processing_time": processing_time
    }

@router.get("/results/{run_id}")
def get_run_results(run_id: int, db: Session = Depends(get_db)):
    run = db.query(CalibrationRun).filter(CalibrationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Calibration run not found.")
        
    # Load raw data
    json_path = os.path.join(RESULTS_DIR, f"run_{run.id}_data.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Detailed data for run not found.")
        
    with open(json_path, "r") as f:
        raw_data = json.load(f)
        
    # Return combined info
    return {
        "id": run.id,
        "timestamp": run.timestamp,
        "sieve_id_tag": run.sieve.sieve_id_tag,
        "sieve_name": run.sieve.name,
        "nominal_size_um": run.sieve.nominal_size_um,
        "state": run.sieve.state,
        "number_of_points": run.number_of_points,
        "area_average": run.area_average,
        "area_min": run.area_min,
        "area_max": run.area_max,
        "area_std": run.area_std,
        "wire_thickness": run.wire_thickness,
        "processing_time": run.processing_time,
        "status": run.status,
        "pixels_per_mm": run.calibration_factor.pixels_per_mm,
        "details": raw_data
    }

@router.get("/history")
def get_history(db: Session = Depends(get_db)):
    runs = db.query(CalibrationRun).order_by(CalibrationRun.timestamp.desc()).all()
    results = []
    for run in runs:
        results.append({
            "id": run.id,
            "timestamp": run.timestamp,
            "sieve_id_tag": run.sieve.sieve_id_tag,
            "sieve_name": run.sieve.name,
            "nominal_size_um": run.sieve.nominal_size_um,
            "state": run.sieve.state,
            "number_of_points": run.number_of_points,
            "area_average": run.area_average,
            "wire_thickness": run.wire_thickness,
            "status": run.status
        })
    return results

@router.get("/results/{run_id}/preview/{stage}")
def get_preview_image(run_id: int, stage: str, image_idx: int = 0):
    """
    Returns original/otsu/filtered preview images for a given run and image index.
    stage: 'original' | 'otsu' | 'filtered'
    """
    json_path = os.path.join(RESULTS_DIR, f"run_{run_id}_data.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Run data not found.")
        
    with open(json_path, "r") as f:
        data = json.load(f)
        
    previews = data.get("previews", [])
    if image_idx >= len(previews):
        raise HTTPException(status_code=404, detail="Image index out of range.")
        
    stage_path = previews[image_idx].get(stage)
    if not stage_path or not os.path.exists(stage_path):
        raise HTTPException(status_code=404, detail=f"Preview stage '{stage}' not found on disk.")
        
    return FileResponse(stage_path)

@router.get("/results/{run_id}/export")
def export_results(run_id: int, format: str = "pdf", db: Session = Depends(get_db)):
    run = db.query(CalibrationRun).filter(CalibrationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
        
    json_path = os.path.join(RESULTS_DIR, f"run_{run.id}_data.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Run details not found.")
    with open(json_path, "r") as f:
        raw_data = json.load(f)
        
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write metadata
        writer.writerow(["SIEVE CALIBRATION CERTIFICATE DATA"])
        writer.writerow([])
        writer.writerow(["Sieve ID Tag", run.sieve.sieve_id_tag])
        writer.writerow(["Sieve Name", run.sieve.name])
        writer.writerow(["Nominal Size (um)", run.sieve.nominal_size_um])
        writer.writerow(["State", run.sieve.state])
        writer.writerow(["Calibration Date", run.timestamp.strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Compliance Status", run.status])
        writer.writerow([])
        writer.writerow(["SUMMARY STATISTICS"])
        writer.writerow(["Total Analyzed Points", run.number_of_points])
        writer.writerow(["Average Area (mm2)", run.area_average])
        writer.writerow(["Min Area (mm2)", run.area_min])
        writer.writerow(["Max Area (mm2)", run.area_max])
        writer.writerow(["Area Std Dev (mm2)", run.area_std])
        writer.writerow(["Measured Avg Opening (um)", raw_data.get("avg_opening_um")])
        writer.writerow(["Measured Max Opening (um)", raw_data.get("max_opening_um")])
        writer.writerow(["Wire Thickness (mm)", run.wire_thickness])
        writer.writerow(["Processing Time (s)", run.processing_time])
        writer.writerow([])
        
        # Write raw areas
        writer.writerow(["INDIVIDUAL DETECTED HOLE AREAS (mm2)"])
        for area in raw_data.get("valid_areas", []):
            writer.writerow([area])
            
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.read().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sieve_{run.sieve.sieve_id_tag}_run_{run_id}.csv"}
        )
        
    elif format == "pdf":
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            from reportlab.lib.units import inch
        except ImportError:
            raise HTTPException(status_code=500, detail="ReportLab library not installed.")
            
        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        story = []
        
        styles = getSampleStyleSheet()
        
        # Custom styles for premium look
        title_style = ParagraphStyle(
            'CertTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=22,
            textColor=colors.HexColor('#0f172a'),
            spaceAfter=15,
            alignment=1 # Centered
        )
        
        subtitle_style = ParagraphStyle(
            'CertSubTitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            textColor=colors.HexColor('#64748b'),
            spaceAfter=25,
            alignment=1
        )
        
        h2_style = ParagraphStyle(
            'CertH2',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            textColor=colors.HexColor('#1e293b'),
            spaceBefore=10,
            spaceAfter=10
        )
        
        body_style = ParagraphStyle(
            'CertBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            textColor=colors.HexColor('#334155'),
            spaceAfter=10
        )
        
        # Header
        story.append(Paragraph("SIEVE CALIBRATION CERTIFICATE", title_style))
        story.append(Paragraph(f"Generated via Machine Vision Expert System | Calibration Date: {run.timestamp.strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
        story.append(Spacer(1, 10))
        
        # Sieve Metadata & Summary Table
        meta_data = [
            [Paragraph("<b>Sieve Specifications</b>", styles['Normal']), Paragraph("<b>Calibration Measurements</b>", styles['Normal'])],
            [
                Paragraph(f"Sieve ID: {run.sieve.sieve_id_tag}<br/>Nominal Size: {run.sieve.nominal_size_um} µm<br/>Sieve Name: {run.sieve.name}<br/>Condition: {run.sieve.state.capitalize()}", body_style),
                Paragraph(f"Analyzed Points: {run.number_of_points} holes<br/>Measured Avg Opening: {raw_data.get('avg_opening_um'):.2f} µm<br/>Measured Max Opening: {raw_data.get('max_opening_um'):.2f} µm<br/>Wire Thickness: {run.wire_thickness:.4f} mm", body_style)
            ]
        ]
        
        meta_table = Table(meta_data, colWidths=[3.5*inch, 3.5*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (1,0), colors.HexColor('#f1f5f9')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 12),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 20))
        
        # Compliance Box
        status_bg = '#dcfce7' if run.status == "Pass" else '#fee2e2'
        status_fg = '#166534' if run.status == "Pass" else '#991b1b'
        compliance_text = f"<b>COMPLIANCE DECISION: {run.status.upper()}</b><br/>"
        if run.status == "Pass":
            compliance_text += "The sieve complies with the ASTM E11 standard. All measured parameters fall within tolerance limits."
        else:
            compliance_text += "The sieve does not comply with the ASTM E11 standard. Measured opening size or maximum opening limits were exceeded."
            
        compliance_data = [[Paragraph(compliance_text, ParagraphStyle('Comp', parent=body_style, textColor=colors.HexColor(status_fg)))]]
        compliance_table = Table(compliance_data, colWidths=[7*inch])
        compliance_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(status_bg)),
            ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor(status_fg)),
            ('PADDING', (0,0), (-1,-1), 12),
        ]))
        story.append(compliance_table)
        story.append(Spacer(1, 25))
        
        # Detailed Stats Table
        story.append(Paragraph("Statistical Breakdown of Hole Area", h2_style))
        stats_data = [
            ["Metric", "Value in mm²", "Equivalent Side Length (µm)"],
            ["Average Area", f"{run.area_average:.6f}", f"{raw_data.get('avg_opening_um'):.2f}"],
            ["Shortest Area", f"{run.area_min:.6f}", f"{math.sqrt(run.area_min)*1000:.2f}"],
            ["Highest Area", f"{run.area_max:.6f}", f"{raw_data.get('max_opening_um'):.2f}"],
            ["Standard Deviation", f"{run.area_std:.6f}", "—"]
        ]
        stats_table = Table(stats_data, colWidths=[2.5*inch, 2.25*inch, 2.25*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0,0), (-1,-1), 8),
            # Set background alternating rows
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#f8fafc')),
            ('BACKGROUND', (0,3), (-1,3), colors.HexColor('#f8fafc')),
        ]))
        # Need to fix text color of headers inside Table
        for i in range(3):
            stats_data[0][i] = Paragraph(f"<font color='white'><b>{stats_data[0][i]}</b></font>", styles['Normal'])
        story.append(stats_table)
        
        story.append(Spacer(1, 40))
        # Sign-off Area
        sign_data = [
            ["", "______________________________"],
            ["", "Calibration Technician Signature"],
            ["", "Sieve Calibration Quality Control Dept"]
        ]
        sign_table = Table(sign_data, colWidths=[4*inch, 3*inch])
        sign_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(sign_table)
        
        doc.build(story)
        pdf_buffer.seek(0)
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=sieve_certificate_{run.sieve.sieve_id_tag}_run_{run_id}.pdf"}
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid export format. Must be 'pdf' or 'csv'.")
