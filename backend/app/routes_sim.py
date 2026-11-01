import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas
from ml import interface as mock_engine
from .database import SessionLocal, get_db

router = APIRouter()


def _run_job(run_id: int):
    """Runs in the background with its own DB session."""
    db = SessionLocal()
    try:
        run = db.get(models.SimulationRun, run_id)
        p = run.params
        time.sleep(1.5)  # fake delay so you can build the 'loading' UI
        if run.kind == "simulate":
            run.result = mock_engine.run_simulation(p["policy"], p["scenario"], p["seed"])
        else:
            run.result = {"results": [
                mock_engine.run_monte_carlo(pk, p["scenario"], p["n_runs"])
                for pk in p["policies"]]}
        run.status = "done"
        db.commit()
    except Exception as e:
        db.rollback()
        run = db.get(models.SimulationRun, run_id)
        run.status = "failed"
        run.error = str(e)
        db.commit()
    finally:
        db.close()


def _create_job(db: Session, kind: str, params: dict, bg: BackgroundTasks):
    run = models.SimulationRun(kind=kind, status="running", params=params)
    db.add(run)
    db.commit()
    db.refresh(run)
    bg.add_task(_run_job, run.id)
    return run


@router.post("/simulate", response_model=schemas.JobOut, status_code=202)
def start_simulation(req: schemas.SimulateRequest, bg: BackgroundTasks,
                     db: Session = Depends(get_db)):
    return _create_job(db, "simulate", req.model_dump(), bg)


@router.post("/montecarlo", response_model=schemas.JobOut, status_code=202)
def start_montecarlo(req: schemas.MonteCarloRequest, bg: BackgroundTasks,
                     db: Session = Depends(get_db)):
    return _create_job(db, "montecarlo", req.model_dump(), bg)


@router.get("/simulate/{job_id}", response_model=schemas.JobOut)
@router.get("/montecarlo/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    run = db.get(models.SimulationRun, job_id)
    if not run:
        raise HTTPException(404, "Job not found")
    return run


@router.get("/compare")
def compare(scenario: str = "baseline", db: Session = Depends(get_db)):
    """Precomputed Monte Carlo KPIs for every policy under one scenario."""
    rows = db.scalars(select(models.KpiResult)
                      .where(models.KpiResult.scenario_key == scenario)).all()
    if not rows:
        raise HTTPException(404, "No results for this scenario")
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r.policy_key, {})[r.metric] = {
            "mean": r.mean, "ci_low": r.ci_low, "ci_high": r.ci_high}
    return {"scenario": scenario, "n_runs": rows[0].n_runs, "policies": out}