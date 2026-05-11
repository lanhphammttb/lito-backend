class ForecastingService:
    @staticmethod
    def estimate_completion_date(total_minutes_needed: int, hours_per_day: float = 4, working_days: int = 5):
        # Simple estimation logic
        from datetime import datetime, timedelta
        capacity_per_week = hours_per_day * 60 * working_days
        weeks_needed = total_minutes_needed / capacity_per_week
        days_needed = weeks_needed * 7
        return datetime.utcnow() + timedelta(days=days_needed)

    @staticmethod
    def calculate_demand_score(views: int, inquiries: int, saves: int):
        # Weights: views(1), saves(2), inquiries(5)
        # Normalize to 0-10 scale based on relative max
        raw_score = views + (saves * 2) + (inquiries * 5)
        # Assume 1000 raw score = 10 points for now
        normalized = min(10.0, (raw_score / 1000) * 10)
        return round(normalized, 1)

    @staticmethod
    def analyze_rfm(recency_days: int, frequency: int, monetary: float):
        # R Score (1-5, 5 is best/lowest days)
        if recency_days <= 14: r_score = 5
        elif recency_days <= 30: r_score = 4
        elif recency_days <= 60: r_score = 3
        elif recency_days <= 90: r_score = 2
        else: r_score = 1
        
        # F Score (1-5)
        if frequency >= 10: f_score = 5
        elif frequency >= 5: f_score = 4
        elif frequency >= 3: f_score = 3
        elif frequency == 2: f_score = 2
        else: f_score = 1
            
        # M Score (1-5)
        if monetary >= 5000000: m_score = 5
        elif monetary >= 2000000: m_score = 4
        elif monetary >= 1000000: m_score = 3
        elif monetary >= 500000: m_score = 2
        else: m_score = 1
            
        return r_score + f_score + m_score
