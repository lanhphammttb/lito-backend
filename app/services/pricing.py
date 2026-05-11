class PricingEngine:
    @staticmethod
    def calculate_material_cost(materials, material_dict):
        total_cost = 0
        for usage in materials:
            mat = material_dict.get(usage.material_id)
            if mat:
                total_cost += mat.unit_price * usage.quantity
        return total_cost

    @staticmethod
    def calculate_labor_cost(time_minutes: int, hourly_rate: float):
        # 80k/h -> ~1333/min
        cost = (hourly_rate / 60) * time_minutes
        # Round to thousands
        return round(cost / 1000) * 1000

    @staticmethod
    def calculate_profit(revenue: float, cost: float, base_profit: float = 0):
        if revenue > 0:
            return revenue - cost
        return base_profit

    @staticmethod
    def calculate_feasibility(profit_per_hour: float, hourly_rate: float, demand_score: float, difficulty: int):
        score = 0
        
        # 1. Profit vs Effort (Max 5 points)
        if profit_per_hour > hourly_rate * 2: score += 5
        elif profit_per_hour > hourly_rate * 1.5: score += 4
        elif profit_per_hour > hourly_rate: score += 3
        elif profit_per_hour > hourly_rate * 0.5: score += 2
        else: score += 1
            
        # 2. Demand (Max 3 points)
        if demand_score > 8: score += 3
        elif demand_score > 5: score += 2
        elif demand_score > 0: score += 1
            
        # 3. Difficulty penalty
        if difficulty <= 2: score += 2
        elif difficulty == 3: score += 1
            
        return score
