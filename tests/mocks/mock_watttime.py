from fastapi import FastAPI
from datetime import datetime
import random

app = FastAPI(title="Mock WattTime API")

@app.get("/v3/signal-index")
async def get_signal_index(latitude: float, longitude: float):
    """Mock real-time carbon intensity"""
    # Simulate different carbon intensities by region
    if longitude < -100:  # West Coast
        base_carbon = 120
    elif longitude < -85:  # Central
        base_carbon = 90
    else:  # East Coast
        base_carbon = 80
    
    # Add time-of-day variation (solar effect)
    hour = datetime.now().hour
    if 10 <= hour <= 16:  # Midday solar
        carbon_factor = 0.7
    else:
        carbon_factor = 1.2
    
    carbon_intensity = base_carbon * carbon_factor + random.uniform(-10, 10)
    
    return {
        "signal_type": "co2_moer",
        "units": "gCO2/kWh", 
        "value": round(carbon_intensity, 1),
        "timestamp": datetime.now().isoformat(),
        "market": "US",
        "frequency": 300
    }

@app.get("/v3/forecast")
async def get_forecast(latitude: float, longitude: float, hours: int = 24):
    """Mock carbon intensity forecast"""
    forecasts = []
    base = 100
    
    for h in range(hours):
        # Simulate daily pattern
        if 6 <= (h % 24) <= 18:
            intensity = base * 0.8  # Lower during solar hours
        else:
            intensity = base * 1.2
            
        forecasts.append({
            "timestamp": f"2024-01-01T{h:02d}:00:00Z",
            "value": round(intensity + random.uniform(-20, 20), 1),
            "units": "gCO2/kWh"
        })
    
    return {"forecasts": forecasts}

@app.get("/v3/verify/{cert_id}")
async def verify_certificate(cert_id: str):
    """Mock certificate verification"""
    return {
        "certificate_id": cert_id,
        "status": "verified",
        "timestamp": datetime.now().isoformat(),
        "carbon_saved": round(random.uniform(100, 500), 1),
        "methodology": "marginal_emissions"
    }