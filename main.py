from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os

from database import engine, get_db
from models import database_models
from routers import calibration, sieve

# Create database tables if they do not exist
database_models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Sieve Calibration System",
    description="Automated machine vision system for sieve calibration",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure static and templates folders exist
os.makedirs("static", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates setting
templates = Jinja2Templates(directory="templates")

# Include Routers
app.include_router(calibration.router)
app.include_router(sieve.router)

# Page Routes
@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/calibrate")
def page_calibrate(request: Request):
    return templates.TemplateResponse(request, "calibrate.html")

@app.get("/analyze")
def page_analyze(request: Request):
    return templates.TemplateResponse(request, "analyze.html")

@app.get("/results/{run_id}")
def page_results(request: Request, run_id: int):
    return templates.TemplateResponse(request, "results.html", {"run_id": run_id})

@app.get("/history")
def page_history(request: Request):
    return templates.TemplateResponse(request, "history.html")

# API Endpoint for Dashboard Stats
@app.get("/api/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    total_sieves = db.query(database_models.Sieve).count()
    total_runs = db.query(database_models.CalibrationRun).count()
    
    pass_runs = db.query(database_models.CalibrationRun).filter(database_models.CalibrationRun.status == "Pass").count()
    pass_rate = (pass_runs / total_runs * 100) if total_runs > 0 else 100.0
    
    latest_runs_db = db.query(database_models.CalibrationRun).order_by(database_models.CalibrationRun.timestamp.desc()).limit(5).all()
    latest_runs = []
    for run in latest_runs_db:
        latest_runs.append({
            "id": run.id,
            "timestamp": run.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "sieve_id_tag": run.sieve.sieve_id_tag,
            "sieve_name": run.sieve.name,
            "nominal_size_um": run.sieve.nominal_size_um,
            "state": run.sieve.state,
            "number_of_points": run.number_of_points,
            "status": run.status
        })
        
    return {
        "total_sieves": total_sieves,
        "total_runs": total_runs,
        "pass_rate": round(pass_rate, 1),
        "latest_runs": latest_runs
    }
