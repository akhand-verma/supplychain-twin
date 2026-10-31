import datetime as dt

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey,
                        Index, Integer, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    unit_cost: Mapped[float] = mapped_column(Float, default=10.0)


class Location(Base):
    """type is one of: supplier, warehouse, store"""
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[float] = mapped_column(Float, default=0)
    x: Mapped[float] = mapped_column(Float, default=0)  # layout position 0-100
    y: Mapped[float] = mapped_column(Float, default=0)


class NetworkEdge(Base):
    __tablename__ = "network_edges"
    id: Mapped[int] = mapped_column(primary_key=True)
    src_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    dst_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    lead_time_mean: Mapped[float] = mapped_column(Float)
    lead_time_std: Mapped[float] = mapped_column(Float)
    cost_per_unit: Mapped[float] = mapped_column(Float)


class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    p10: Mapped[float] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float)
    p90: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index("ix_fc_pair", "location_id", "product_id", "date"),)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    on_hand: Mapped[float] = mapped_column(Float)
    demand: Mapped[float] = mapped_column(Float)
    days_cover: Mapped[float] = mapped_column(Float)
    stockout: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("ix_inv_pair", "location_id", "product_id", "date"),)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)


class SimulationRun(Base):
    """A background job. kind = 'simulate' or 'montecarlo'."""
    __tablename__ = "simulation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="running")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class KpiResult(Base):
    """Precomputed Monte Carlo results: one row per policy/scenario/metric."""
    __tablename__ = "kpi_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(50))
    scenario_key: Mapped[str] = mapped_column(String(50))
    metric: Mapped[str] = mapped_column(String(50))
    mean: Mapped[float] = mapped_column(Float)
    ci_low: Mapped[float] = mapped_column(Float)
    ci_high: Mapped[float] = mapped_column(Float)
    n_runs: Mapped[int] = mapped_column(Integer)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    severity: Mapped[str] = mapped_column(String(10))  # high / medium
    message: Mapped[str] = mapped_column(Text)
    recommended_qty: Mapped[int] = mapped_column(Integer)