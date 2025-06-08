"""
GridSynapse Optimization Solver
Dual-commodity (price + carbon) optimization using Google OR-Tools
Target: <100ms solver time for investor demos
"""

from ortools.linear_solver import pywraplp
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import time
import redis
import json
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Job:
    """AI workload job"""
    job_id: str
    compute_units: int
    duration_hours: float
    flexibility_window: int
    carbon_neutral: bool
    value: float  # Revenue per hour

@dataclass
class Datacenter:
    """Datacenter with capacity and pricing"""
    dc_id: str
    capacity_units: int
    location: str
    prices: List[float]  # Hourly prices
    carbon_intensity: List[float]  # Hourly carbon intensity

@dataclass
class OptimizationResult:
    """Result from optimization solver"""
    success: bool
    solve_time_ms: float
    total_cost: float
    total_carbon: float
    total_revenue: float
    schedule: List[Dict]
    solver_status: str

class GridSynapseOptimizer:
    """
    Fast dual-commodity optimizer for GridSynapse
    Optimizes for both cost and carbon emissions
    """
    
    def __init__(self, redis_host: str = "redis", redis_port: int = 6379):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.solver = None
        
    def optimize(
        self,
        jobs: List[Job],
        datacenters: List[Datacenter],
        time_horizon_hours: int = 24,
        carbon_weight: float = 0.3
    ) -> OptimizationResult:
        """
        Run optimization to schedule jobs across datacenters
        
        Args:
            jobs: List of jobs to schedule
            datacenters: Available datacenters
            time_horizon_hours: Planning horizon
            carbon_weight: Weight for carbon vs cost (0-1)
        
        Returns:
            OptimizationResult with schedule and metrics
        """
        start_time = time.time()
        
        # Create solver
        self.solver = pywraplp.Solver.CreateSolver('GLOP')
        if not self.solver:
            return OptimizationResult(
                success=False,
                solve_time_ms=0,
                total_cost=0,
                total_carbon=0,
                total_revenue=0,
                schedule=[],
                solver_status="Failed to create solver"
            )
        
        # Decision variables: x[j,d,t] = 1 if job j runs on datacenter d at time t
        x = {}
        for j, job in enumerate(jobs):
            for d, dc in enumerate(datacenters):
                for t in range(time_horizon_hours):
                    x[j, d, t] = self.solver.IntVar(0, 1, f'x_{j}_{d}_{t}')
        
        # Objective: Minimize (cost - revenue) + carbon_weight * carbon_emissions
        objective = self.solver.Objective()
        
        for j, job in enumerate(jobs):
            for d, dc in enumerate(datacenters):
                for t in range(time_horizon_hours):
                    # Cost component
                    cost = job.compute_units * dc.prices[t % len(dc.prices)]
                    revenue = job.value * job.compute_units
                    
                    # Carbon component
                    carbon = job.compute_units * dc.carbon_intensity[t % len(dc.carbon_intensity)]
                    
                    # Combined objective
                    coefficient = (cost - revenue) + carbon_weight * carbon
                    objective.SetCoefficient(x[j, d, t], coefficient)
        
        objective.SetMinimization()
        
        # Constraints
        
        # 1. Each job must be scheduled exactly once
        for j, job in enumerate(jobs):
            constraint = self.solver.Constraint(1, 1)
            for d in range(len(datacenters)):
                for t in range(time_horizon_hours - int(job.duration_hours) + 1):
                    constraint.SetCoefficient(x[j, d, t], 1)
        
        # 2. Datacenter capacity constraints
        for d, dc in enumerate(datacenters):
            for t in range(time_horizon_hours):
                constraint = self.solver.Constraint(0, dc.capacity_units)
                for j, job in enumerate(jobs):
                    # Check if job would be running at time t
                    for start_t in range(max(0, t - int(job.duration_hours) + 1), t + 1):
                        if start_t + job.duration_hours > t:
                            constraint.SetCoefficient(x[j, d, start_t], job.compute_units)
        
        # 3. Job flexibility window constraints
        for j, job in enumerate(jobs):
            for d in range(len(datacenters)):
                for t in range(time_horizon_hours):
                    if t > job.flexibility_window:
                        x[j, d, t].SetBounds(0, 0)
        
        # 4. Carbon neutral jobs must use low-carbon datacenters
        for j, job in enumerate(jobs):
            if job.carbon_neutral:
                for d, dc in enumerate(datacenters):
                    for t in range(time_horizon_hours):
                        if dc.carbon_intensity[t % len(dc.carbon_intensity)] > 100:  # threshold
                            x[j, d, t].SetBounds(0, 0)
        
        # Solve
        logger.info(f"Solving optimization with {len(jobs)} jobs and {len(datacenters)} datacenters")
        status = self.solver.Solve()
        
        solve_time_ms = (time.time() - start_time) * 1000
        
        # Extract results
        if status == pywraplp.Solver.OPTIMAL:
            schedule = []
            total_cost = 0
            total_carbon = 0
            total_revenue = 0
            
            for j, job in enumerate(jobs):
                for d, dc in enumerate(datacenters):
                    for t in range(time_horizon_hours):
                        if x[j, d, t].solution_value() > 0.5:
                            cost = job.compute_units * job.duration_hours * dc.prices[t % len(dc.prices)]
                            carbon = job.compute_units * job.duration_hours * dc.carbon_intensity[t % len(dc.carbon_intensity)]
                            revenue = job.value * job.compute_units * job.duration_hours
                            
                            schedule.append({
                                "job_id": job.job_id,
                                "datacenter_id": dc.dc_id,
                                "start_time": t,
                                "end_time": t + job.duration_hours,
                                "cost": cost,
                                "carbon_kg": carbon,
                                "revenue": revenue
                            })
                            
                            total_cost += cost
                            total_carbon += carbon
                            total_revenue += revenue
            
            return OptimizationResult(
                success=True,
                solve_time_ms=solve_time_ms,
                total_cost=total_cost,
                total_carbon=total_carbon,
                total_revenue=total_revenue,
                schedule=sorted(schedule, key=lambda x: x["start_time"]),
                solver_status="OPTIMAL"
            )
        else:
            return OptimizationResult(
                success=False,
                solve_time_ms=solve_time_ms,
                total_cost=0,
                total_carbon=0,
                total_revenue=0,
                schedule=[],
                solver_status=f"Solver status: {status}"
            )
    
    def create_demo_scenario(self) -> Tuple[List[Job], List[Datacenter]]:
        """Create a demo scenario for investor presentations"""
        
        # Demo jobs - mix of AI workloads
        jobs = [
            Job("llm-training-1", 100, 4.0, 12, True, 50.0),
            Job("inference-batch-1", 50, 2.0, 24, False, 30.0),
            Job("fine-tuning-1", 75, 3.0, 8, True, 40.0),
            Job("embedding-gen-1", 25, 1.0, 24, False, 20.0),
            Job("model-serving-1", 150, 6.0, 6, True, 60.0),
        ]
        
        # Demo datacenters across US
        datacenters = [
            Datacenter(
                "us-west-2a",
                300,
                "Oregon",
                [0.08, 0.09, 0.10, 0.12, 0.15, 0.14, 0.12, 0.10] * 3,  # 24 hours
                [50, 60, 70, 80, 90, 85, 75, 65] * 3  # Low carbon (hydro)
            ),
            Datacenter(
                "us-east-1a", 
                250,
                "Virginia",
                [0.10, 0.11, 0.13, 0.15, 0.18, 0.17, 0.14, 0.12] * 3,
                [120, 130, 140, 150, 160, 155, 145, 135] * 3  # Higher carbon
            ),
            Datacenter(
                "us-central-1a",
                200, 
                "Iowa",
                [0.07, 0.08, 0.09, 0.11, 0.13, 0.12, 0.10, 0.09] * 3,
                [30, 35, 40, 45, 50, 48, 42, 38] * 3  # Very low carbon (wind)
            ),
        ]
        
        return jobs, datacenters
    
    async def run_continuous_optimization(self):
        """Run optimization continuously, processing jobs from Redis queue"""
        logger.info("Starting continuous optimization loop")
        
        while True:
            try:
                # Get jobs from queue
                job_ids = []
                for _ in range(10):  # Process up to 10 jobs at a time
                    job_id = self.redis_client.rpop("job_queue")
                    if job_id:
                        job_ids.append(job_id)
                
                if job_ids:
                    logger.info(f"Processing {len(job_ids)} jobs")
                    
                    # For demo, use mock scenario
                    jobs, datacenters = self.create_demo_scenario()
                    
                    # Run optimization
                    result = self.optimize(jobs[:len(job_ids)], datacenters)
                    
                    if result.success:
                        logger.info(f"Optimization successful: {result.solve_time_ms:.1f}ms")
                        
                        # Store results in Redis
                        for schedule_item in result.schedule:
                            self.redis_client.setex(
                                f"schedule:{schedule_item['job_id']}",
                                3600 * 24,
                                json.dumps(schedule_item)
                            )
                    else:
                        logger.error(f"Optimization failed: {result.solver_status}")
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in optimization loop: {e}")
                await asyncio.sleep(10)

def run_demo():
    """Run a demo optimization for testing"""
    optimizer = GridSynapseOptimizer()
    jobs, datacenters = optimizer.create_demo_scenario()
    
    print("\n🎯 Running GridSynapse Optimization Demo...")
    print(f"📊 Optimizing {len(jobs)} AI workloads across {len(datacenters)} datacenters")
    
    result = optimizer.optimize(jobs, datacenters, carbon_weight=0.4)
    
    if result.success:
        print(f"\n✅ Optimization completed in {result.solve_time_ms:.1f}ms")
        print(f"💰 Total cost: ${result.total_cost:.2f}")
        print(f"🌱 Carbon emissions: {result.total_carbon:.1f} kg CO2")
        print(f"📈 Total revenue: ${result.total_revenue:.2f}")
        print(f"💵 Net savings: ${result.total_revenue - result.total_cost:.2f}")
        
        print("\n📅 Optimized Schedule:")
        for item in result.schedule:
            print(f"  Job {item['job_id']}: {item['datacenter_id']} at hour {item['start_time']}")
            print(f"    Cost: ${item['cost']:.2f}, Carbon: {item['carbon_kg']:.1f} kg")
    else:
        print(f"\n❌ Optimization failed: {result.solver_status}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        run_demo()
    else:
        # Run continuous optimization service
        optimizer = GridSynapseOptimizer()
        asyncio.run(optimizer.run_continuous_optimization())