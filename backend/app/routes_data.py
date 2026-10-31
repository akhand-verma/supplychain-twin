import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .database import get_db

router = APIRouter()


@router.get("/products")
def products(db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Product).order_by(models.Product.id))
    return [{"id": p.id, "name": p.name, "category": p.category} for p in rows]


@router.get("/locations")
def locations(type: str | None = None, db: Session = Depends(get_db)):
    q = select(models.Location).order_by(models.Location.id)
    if type:
        q = q.where(models.Location.type == type)
    return [{"id": loc.id, "name": loc.name, "type": loc.type} for loc in db.scalars(q)]


@router.get("/policies")
def policies(db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Policy).order_by(models.Policy.id))
    return [{"key": p.key, "name": p.name, "description": p.description} for p in rows]


@router.get("/scenarios")
def scenarios(db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Scenario).order_by(models.Scenario.id))
    return [{"key": s.key, "name": s.name, "description": s.description,
             "params": s.params} for s in rows]


@router.get("/network")
def network(db: Session = Depends(get_db)):
    locs = db.scalars(select(models.Location)).all()
    edges = db.scalars(select(models.NetworkEdge)).all()
    last = db.scalar(select(func.max(models.InventorySnapshot.date)))
    snaps = []
    if last:
        snaps = db.scalars(select(models.InventorySnapshot)
                           .where(models.InventorySnapshot.date == last)).all()
    by_loc: dict[int, list] = {}
    for s in snaps:
        by_loc.setdefault(s.location_id, []).append(s)

    nodes = []
    for loc in locs:
        ss = by_loc.get(loc.id, [])
        stockouts = sum(1 for s in ss if s.stockout)
        low = sum(1 for s in ss if s.days_cover < 3)
        health = "red" if (stockouts or low >= 3) else ("yellow" if low else "green")
        nodes.append({
            "id": loc.id, "name": loc.name, "type": loc.type, "x": loc.x, "y": loc.y,
            "health": health, "stockouts": stockouts, "low_stock_items": low,
            "total_on_hand": round(sum(s.on_hand for s in ss)),
        })
    return {
        "as_of": last.isoformat() if last else None,
        "nodes": nodes,
        "edges": [{"id": e.id, "src": e.src_id, "dst": e.dst_id,
                   "lead_time_mean": e.lead_time_mean,
                   "lead_time_std": e.lead_time_std} for e in edges],
    }


@router.get("/inventory/{location_id}/{product_id}")
def inventory(location_id: int, product_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(models.InventorySnapshot)
        .where(models.InventorySnapshot.location_id == location_id,
               models.InventorySnapshot.product_id == product_id)
        .order_by(models.InventorySnapshot.date)).all()
    if not rows:
        raise HTTPException(404, "No inventory data for this location/product")
    return [{"date": r.date.isoformat(), "on_hand": r.on_hand, "demand": r.demand,
             "days_cover": round(r.days_cover, 2), "stockout": r.stockout} for r in rows]


@router.get("/forecast/{location_id}/{product_id}")
def forecast(location_id: int, product_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(models.Forecast)
        .where(models.Forecast.location_id == location_id,
               models.Forecast.product_id == product_id)
        .order_by(models.Forecast.date)).all()
    if not rows:
        raise HTTPException(404, "No forecast for this location/product")
    return [{"date": r.date.isoformat(), "p10": round(r.p10, 1),
             "p50": round(r.p50, 1), "p90": round(r.p90, 1)} for r in rows]


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)):
    q = (select(models.Alert, models.Location.name, models.Product.name)
         .join(models.Location, models.Alert.location_id == models.Location.id)
         .join(models.Product, models.Alert.product_id == models.Product.id)
         .order_by(models.Alert.severity, models.Alert.id))
    out = []
    for a, loc_name, prod_name in db.execute(q):
        out.append({"id": a.id, "location_id": a.location_id, "location": loc_name,
                    "product_id": a.product_id, "product": prod_name,
                    "date": a.date.isoformat(), "severity": a.severity,
                    "message": a.message, "recommended_qty": a.recommended_qty})
    return out


@router.get("/explain/{location_id}/{product_id}")
def explain(location_id: int, product_id: int, db: Session = Depends(get_db)):
    """'Why this order quantity?' (mock logic; Person A supplies the real one later)"""
    snap = db.scalars(
        select(models.InventorySnapshot)
        .where(models.InventorySnapshot.location_id == location_id,
               models.InventorySnapshot.product_id == product_id)
        .order_by(models.InventorySnapshot.date.desc()).limit(1)).first()
    if not snap:
        raise HTTPException(404, "No inventory for this location/product")
    edge = db.scalars(select(models.NetworkEdge)
                      .where(models.NetworkEdge.dst_id == location_id)
                      .order_by(models.NetworkEdge.id)).first()
    lead = max(1, round(edge.lead_time_mean)) if edge else 3
    fcs = db.scalars(
        select(models.Forecast)
        .where(models.Forecast.location_id == location_id,
               models.Forecast.product_id == product_id,
               models.Forecast.date > snap.date)
        .order_by(models.Forecast.date).limit(lead)).all()
    if not fcs:
        raise HTTPException(404, "No future forecast available")

    exp_demand = sum(f.p50 for f in fcs)
    p90_demand = sum(f.p90 for f in fcs)
    safety = max(0.0, p90_demand - exp_demand)
    qty = max(0, math.ceil(exp_demand + safety - snap.on_hand))
    return {
        "location_id": location_id, "product_id": product_id,
        "on_hand": round(snap.on_hand), "lead_time_days": lead,
        "expected_demand_over_lead_time": round(exp_demand),
        "p90_demand_over_lead_time": round(p90_demand),
        "safety_stock": round(safety), "service_target": 0.90,
        "recommended_order_qty": qty,
        "reason": (f"Lead time is {lead} days. Expected demand in that window is "
                   f"{round(exp_demand)} units (P90: {round(p90_demand)}). "
                   f"Stock on hand is {round(snap.on_hand)}, so order {qty} units "
                   f"to cover demand plus {round(safety)} units of safety stock."),
    }