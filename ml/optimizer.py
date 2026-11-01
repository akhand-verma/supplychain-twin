import os
import json
import pulp

ARTIFACTS_DIR = "ml/artifacts"


class SupplyChainOptimizer:
    def __init__(self):
        with open(os.path.join(ARTIFACTS_DIR, "network_topology.json"), "r") as f:
            self.topology = json.load(f)

    def optimize_redistribution(self, current_inventories, current_demands):
        prob = pulp.LpProblem("SupplyChain_Clustered_Redistribution", pulp.LpMinimize)

        stores = self.topology["metadata"]["stores"]
        warehouses = [n["id"] for n in self.topology["nodes"] if n["type"] == "warehouse"]
        all_nodes = warehouses + stores
        cost_matrix = self.topology.get("transfer_cost_matrix", {})

        node_penalties = {
            n["id"]: n.get("stockout_penalty", 5.00)
            for n in self.topology["nodes"] if n["type"] == "store"
        }

        ship_vars = {}
        for i in all_nodes:
            for j in stores:
                if i != j:
                    ship_vars[(i, j)] = pulp.LpVariable(f"ship_{i}_{j}", lowBound=0, cat="Continuous")

        shortage_vars = {
            s: pulp.LpVariable(f"shortage_{s}", lowBound=0, cat="Continuous") for s in stores
        }

        # Objective: Distance-clustered transport cost + store-specific stockout penalty
        total_transport = pulp.lpSum(
            ship_vars[(i, j)] * cost_matrix.get(i, {}).get(j, 0.50)
            for (i, j) in ship_vars
        )
        total_shortage = pulp.lpSum(
            shortage_vars[s] * node_penalties.get(s, 5.00) for s in stores
        )

        prob += total_transport + total_shortage, "Total_Redistribution_Cost"

        for i in all_nodes:
            outflow = pulp.lpSum(ship_vars[(i, j)] for j in stores if (i, j) in ship_vars)
            avail = current_inventories.get(i, 0)
            prob += outflow <= avail, f"Stock_Limit_{i}"

        for s in stores:
            inflow = pulp.lpSum(ship_vars[(i, s)] for i in all_nodes if (i, s) in ship_vars)
            outflow_s = pulp.lpSum(ship_vars[(s, j)] for j in stores if (s, j) in ship_vars)
            demand = current_demands.get(s, 20)
            starting_s = current_inventories.get(s, 0)
            prob += starting_s + inflow - outflow_s + shortage_vars[s] >= demand, f"Demand_Satisfy_{s}"

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        status = pulp.LpStatus[prob.status]
        transfers = []
        if status == "Optimal":
            for (i, j), var in ship_vars.items():
                if var.varValue and var.varValue > 0.01:
                    unit_cost = cost_matrix.get(i, {}).get(j, 0.50)
                    transfers.append({
                        "from": i,
                        "to": j,
                        "qty": round(float(var.varValue), 2),
                        "unit_transport_cost": unit_cost,
                    })

        return {
            "status": status,
            "optimal_transfers": transfers,
            "total_optimization_cost": round(float(pulp.value(prob.objective)), 2),
        }


if __name__ == "__main__":
    opt = SupplyChainOptimizer()
    mock_inv = {"WH_WEST": 500, "WH_CENTRAL": 600, "CA_1": 10, "CA_2": 5, "TX_1": 150, "TX_2": 120, "WI_1": 200, "WI_2": 180}
    mock_dem = {"CA_1": 80, "CA_2": 70, "TX_1": 40, "TX_2": 30, "WI_1": 25, "WI_2": 20}
    print(json.dumps(opt.optimize_redistribution(mock_inv, mock_dem), indent=2))