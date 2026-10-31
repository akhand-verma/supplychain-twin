POLICIES = [
    {"key": "fixed_order", "name": "Fixed order quantity",
     "description": "Baseline: orders a fixed amount on a fixed schedule, ignoring forecasts."},
    {"key": "s_S", "name": "(s,S) policy",
     "description": "Reorders up to S when stock falls to s. Levels set from average demand."},
    {"key": "newsvendor", "name": "Forecast-driven newsvendor",
     "description": "Orders up to a forecast quantile chosen from stockout vs holding cost."},
    {"key": "newsvendor_milp", "name": "Newsvendor + MILP redistribution",
     "description": "Newsvendor ordering plus optimal stock transfers when a disruption hits."},
]

SCENARIOS = [
    {"key": "baseline", "name": "No disruption", "description": "Normal operations.",
     "params": {"type": "none"}},
    {"key": "supplier_outage", "name": "Supplier outage (10 days)",
     "description": "Supplier A stops delivering for 10 days.",
     "params": {"type": "supplier_outage", "supplier_id": 1, "days": 10}},
    {"key": "transport_delay", "name": "Transport delay (2x lead time)",
     "description": "All lead times double for 8 days.",
     "params": {"type": "transport_delay", "multiplier": 2.0, "days": 8}},
    {"key": "warehouse_down", "name": "Warehouse shutdown (7 days)",
     "description": "Warehouse 1 is offline for 7 days.",
     "params": {"type": "warehouse_down", "warehouse_id": 3, "days": 7}},
    {"key": "demand_spike", "name": "Demand spike (+60%)",
     "description": "Demand jumps 60% for 6 days.",
     "params": {"type": "demand_spike", "multiplier": 1.6, "days": 6}},
    {"key": "compound", "name": "Compound: supplier + delay",
     "description": "Supplier outage and transport delay at the same time.",
     "params": {"type": "compound", "parts": ["supplier_outage", "transport_delay"]}},
]

POLICY_KEYS = [p["key"] for p in POLICIES]
SCENARIO_KEYS = [s["key"] for s in SCENARIOS]