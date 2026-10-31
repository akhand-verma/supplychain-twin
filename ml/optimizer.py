import os
import json
import pulp

ARTIFACTS_DIR = "ml/artifacts"

class SupplyChainOptimizer:
    def __init__(self):
        with open(os.path.join(ARTIFACTS_DIR, "network_topology.json"), "r") as f:
            self.topology = json.load(f)
            
    def optimize_redistribution(self, current_inventories, current_demands):
        """
        Solves a MILP optimization problem to redistribute inventory 
        across warehouses and stores during disruptions.
        
        current_inventories: dict of {node_id: stock_qty}
        current_demands: dict of {store_id: expected_demand}
        """
        prob = pulp.LpProblem("SupplyChain_Redistribution", pulp.LpMinimize)

        stores = self.topology["metadata"]["stores"]
        warehouses = [n["id"] for n in self.topology["nodes"] if n["type"] == "warehouse"]
        all_nodes = warehouses + stores

        # Decision variables: quantity shipped from node i to node j
        ship_vars = {}
        for i in all_nodes:
            for j in stores:
                if i != j:
                    ship_vars[(i, j)] = pulp.LpVariable(f"ship_{i}_{j}", lowBound=0, cat="Continuous")

        # Unmet demand shortage variable per store
        shortage_vars = {s: pulp.LpVariable(f"shortage_{s}", lowBound=0, cat="Continuous") for s in stores}

        # Objective Function: Minimize transport cost + stockout penalty
        transport_cost_per_unit = 0.50
        stockout_penalty = 5.00

        total_transport = pulp.lpSum(ship_vars[(i, j)] * transport_cost_per_unit for i, j in ship_vars)
        total_shortage = pulp.lpSum(shortage_vars[s] * stockout_penalty for s in stores)
        
        prob += total_transport + total_shortage, "Total_Cost"

        # Constraints per node: Outflow cannot exceed available stock
        for i in all_nodes:
            outflow = pulp.lpSum(ship_vars[(i, j)] for j in stores if (i, j) in ship_vars)
            avail = current_inventories.get(i, 0)
            prob += outflow <= avail, f"Stock_Limit_{i}"

        # Demand satisfaction constraints per store
        for s in stores:
            inflow = pulp.lpSum(ship_vars[(i, s)] for i in all_nodes if (i, s) in ship_vars)
            demand = current_demands.get(s, 20)
            
            # Stock received + starting stock + shortage >= demand
            starting_s = current_inventories.get(s, 0)
            prob += starting_s + inflow + shortage_vars[s] >= demand, f"Demand_Satisfy_{s}"

        # Solve using PuLP's default CBC solver
        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        status = pulp.LpStatus[prob.status]
        transfers = []
        if status == "Optimal":
            for (i, j), var in ship_vars.items():
                if var.varValue > 0.01:
                    transfers.append({"from": i, "to": j, "qty": round(float(var.varValue), 2)})

        return {
            "status": status,
            "optimal_transfers": transfers,
            "total_optimization_cost": round(float(pulp.value(prob.objective)), 2)
        }

if __name__ == "__main__":
    opt = SupplyChainOptimizer()
    mock_inv = {"WH_WEST": 500, "WH_CENTRAL": 600, "CA_1": 10, "CA_2": 5, "TX_1": 150, "TX_2": 120, "WI_1": 200, "WI_2": 180}
    mock_dem = {"CA_1": 80, "CA_2": 70, "TX_1": 40, "TX_2": 30, "WI_1": 25, "WI_2": 20}
    
    res = opt.optimize_redistribution(mock_inv, mock_dem)
    print("MILP Optimizer Sanity Test Result:")
    print(json.dumps(res, indent=2))