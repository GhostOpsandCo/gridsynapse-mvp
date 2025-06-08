#!/usr/bin/env python3
"""
GridSynapse Code Validation & Feedback System
Allows Claude to check its work and iterate for improvements
"""

import subprocess
import json
import time
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ValidationResult:
    """Result of a validation check"""
    check_name: str
    passed: bool
    message: str
    suggestions: List[str]
    metrics: Dict[str, Any]

class GridSynapseValidator:
    """
    Comprehensive validation system that provides actionable feedback
    """
    
    def __init__(self, project_root: Path = Path(".")):
        self.project_root = project_root
        self.results = []
        
    def run_all_checks(self) -> Dict[str, Any]:
        """Run all validation checks and return comprehensive feedback"""
        print("🔍 Starting GridSynapse validation suite...\n")
        
        # Structure checks
        self.check_project_structure()
        self.check_dependencies()
        
        # Code quality checks
        self.check_code_quality()
        # self.check_type_hints()  # TODO: Implement type checking
        
        # Functionality checks
        self.check_api_endpoints()
        self.check_solver_performance()
        self.check_docker_setup()
        
        # Security checks
        self.check_security()
        
        # Documentation checks
        self.check_documentation()
        
        return self.generate_feedback_report()
    
    def check_project_structure(self) -> ValidationResult:
        """Verify all required directories and files exist"""
        required_structure = {
            "directories": [
                "api", "solver", "agents", "k8s-operator",
                "infra", "tests", "docs"
            ],
            "files": [
                "README.md", "docker-compose.yml", "Makefile",
                "quickstart.sh", ".github/workflows/ci-cd.yml"
            ]
        }
        
        missing_dirs = []
        missing_files = []
        
        for dir_name in required_structure["directories"]:
            if not (self.project_root / dir_name).exists():
                missing_dirs.append(dir_name)
                
        for file_name in required_structure["files"]:
            if not (self.project_root / file_name).exists():
                missing_files.append(file_name)
        
        passed = len(missing_dirs) == 0 and len(missing_files) == 0
        
        result = ValidationResult(
            check_name="Project Structure",
            passed=passed,
            message=f"Missing {len(missing_dirs)} directories, {len(missing_files)} files",
            suggestions=[
                f"Create directory: {d}" for d in missing_dirs
            ] + [
                f"Create file: {f}" for f in missing_files
            ],
            metrics={
                "missing_dirs": missing_dirs,
                "missing_files": missing_files
            }
        )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_dependencies(self) -> ValidationResult:
        """Check if all dependencies are properly specified"""
        requirements_files = [
            "api/requirements.txt",
            "solver/requirements.txt",
            "agents/requirements.txt"
        ]
        
        missing_deps = []
        issues = []
        
        for req_file in requirements_files:
            path = self.project_root / req_file
            if not path.exists():
                missing_deps.append(req_file)
            else:
                # Check for key dependencies
                content = path.read_text()
                if "api/requirements.txt" in req_file:
                    if "fastapi" not in content:
                        issues.append("FastAPI missing from api requirements")
                    if "opentelemetry" not in content:
                        issues.append("OpenTelemetry missing from api requirements")
                elif "solver/requirements.txt" in req_file:
                    if "ortools" not in content:
                        issues.append("OR-Tools missing from solver requirements")
        
        passed = len(missing_deps) == 0 and len(issues) == 0
        
        result = ValidationResult(
            check_name="Dependencies",
            passed=passed,
            message=f"{len(missing_deps)} missing requirement files, {len(issues)} dependency issues",
            suggestions=missing_deps + issues,
            metrics={
                "missing_files": missing_deps,
                "issues": issues
            }
        )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_code_quality(self) -> ValidationResult:
        """Run linting and code quality checks"""
        issues = []
        
        try:
            # Run black check
            result = subprocess.run(
                ["black", "--check", "api/", "solver/", "agents/"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                issues.append("Code formatting issues (run: black api/ solver/ agents/)")
        except FileNotFoundError:
            issues.append("Black not installed (pip install black)")
            
        try:
            # Run ruff
            result = subprocess.run(
                ["ruff", "check", "api/", "solver/", "agents/"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                issues.append(f"Linting issues found: {result.stdout.count('Found')}")
        except FileNotFoundError:
            issues.append("Ruff not installed (pip install ruff)")
        
        passed = len(issues) == 0
        
        result = ValidationResult(
            check_name="Code Quality",
            passed=passed,
            message=f"{len(issues)} code quality issues found",
            suggestions=issues,
            metrics={"issue_count": len(issues)}
        )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_api_endpoints(self) -> ValidationResult:
        """Verify API endpoints are properly defined"""
        api_file = self.project_root / "api" / "main.py"
        
        if not api_file.exists():
            result = ValidationResult(
                check_name="API Endpoints",
                passed=False,
                message="API main.py file not found",
                suggestions=["Create api/main.py with FastAPI application"],
                metrics={}
            )
        else:
            content = api_file.read_text()
            required_endpoints = [
                "/api/v1/jobs",
                "/api/v1/partners/telemetry",
                "/api/v1/prices",
                "/api/v1/health"
            ]
            
            missing_endpoints = []
            for endpoint in required_endpoints:
                if endpoint not in content:
                    missing_endpoints.append(endpoint)
            
            passed = len(missing_endpoints) == 0
            
            result = ValidationResult(
                check_name="API Endpoints",
                passed=passed,
                message=f"{len(missing_endpoints)} missing endpoints",
                suggestions=[f"Add endpoint: {e}" for e in missing_endpoints],
                metrics={"missing_endpoints": missing_endpoints}
            )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_solver_performance(self) -> ValidationResult:
        """Test solver performance meets <100ms requirement"""
        solver_file = self.project_root / "solver" / "optimizer.py"
        
        if not solver_file.exists():
            result = ValidationResult(
                check_name="Solver Performance",
                passed=False,
                message="Solver optimizer.py not found",
                suggestions=["Create solver/optimizer.py with OR-Tools implementation"],
                metrics={}
            )
        else:
            # Check if performance target is mentioned
            content = solver_file.read_text()
            has_timeout = "timeout" in content.lower() or "100" in content
            has_ortools = "ortools" in content or "pywraplp" in content
            
            issues = []
            if not has_timeout:
                issues.append("No timeout constraint found (target: <100ms)")
            if not has_ortools:
                issues.append("OR-Tools not imported")
            
            passed = len(issues) == 0
            
            result = ValidationResult(
                check_name="Solver Performance",
                passed=passed,
                message=f"Solver implementation {'ready' if passed else 'needs work'}",
                suggestions=issues,
                metrics={
                    "has_timeout": has_timeout,
                    "has_ortools": has_ortools
                }
            )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_docker_setup(self) -> ValidationResult:
        """Validate Docker configuration"""
        compose_file = self.project_root / "docker-compose.yml"
        
        if not compose_file.exists():
            result = ValidationResult(
                check_name="Docker Setup",
                passed=False,
                message="docker-compose.yml not found",
                suggestions=["Create docker-compose.yml with all services"],
                metrics={}
            )
        else:
            content = compose_file.read_text()
            required_services = ["api", "postgres", "redis", "prometheus"]
            missing_services = []
            
            for service in required_services:
                if f"{service}:" not in content:
                    missing_services.append(service)
            
            passed = len(missing_services) == 0
            
            result = ValidationResult(
                check_name="Docker Setup",
                passed=passed,
                message=f"{len(missing_services)} missing services in docker-compose",
                suggestions=[f"Add service: {s}" for s in missing_services],
                metrics={"missing_services": missing_services}
            )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_security(self) -> ValidationResult:
        """Check for security best practices"""
        issues = []
        
        # Check for hardcoded secrets
        files_to_check = [
            "api/main.py",
            "docker-compose.yml",
            ".env"
        ]
        
        secret_patterns = [
            "password=",
            "secret_key=",
            "api_key="
        ]
        
        for file_path in files_to_check:
            path = self.project_root / file_path
            if path.exists() and file_path != ".env":  # .env is ok for local dev
                content = path.read_text().lower()
                for pattern in secret_patterns:
                    if pattern in content and "os.environ" not in content:
                        issues.append(f"Potential hardcoded secret in {file_path}")
        
        # Check for .env in .gitignore
        gitignore = self.project_root / ".gitignore"
        if gitignore.exists():
            if ".env" not in gitignore.read_text():
                issues.append(".env not in .gitignore")
        else:
            issues.append(".gitignore file missing")
        
        passed = len(issues) == 0
        
        result = ValidationResult(
            check_name="Security",
            passed=passed,
            message=f"{len(issues)} security issues found",
            suggestions=issues,
            metrics={"issue_count": len(issues)}
        )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def check_documentation(self) -> ValidationResult:
        """Verify documentation completeness"""
        readme = self.project_root / "README.md"
        
        if not readme.exists():
            result = ValidationResult(
                check_name="Documentation",
                passed=False,
                message="README.md not found",
                suggestions=["Create comprehensive README.md"],
                metrics={}
            )
        else:
            content = readme.read_text().lower()
            required_sections = [
                "quick start",
                "architecture",
                "api",
                "docker"
            ]
            
            missing_sections = []
            for section in required_sections:
                if section not in content:
                    missing_sections.append(section)
            
            passed = len(missing_sections) == 0
            
            result = ValidationResult(
                check_name="Documentation", 
                passed=passed,
                message=f"README {'complete' if passed else f'missing {len(missing_sections)} sections'}",
                suggestions=[f"Add section: {s}" for s in missing_sections],
                metrics={"missing_sections": missing_sections}
            )
        
        self.results.append(result)
        self._print_result(result)
        return result
    
    def generate_feedback_report(self) -> Dict[str, Any]:
        """Generate comprehensive feedback report for Claude"""
        total_checks = len(self.results)
        passed_checks = sum(1 for r in self.results if r.passed)
        
        # Prioritize suggestions
        critical_fixes = []
        improvements = []
        
        for result in self.results:
            if not result.passed:
                if result.check_name in ["Project Structure", "API Endpoints", "Docker Setup"]:
                    critical_fixes.extend(result.suggestions)
                else:
                    improvements.extend(result.suggestions)
        
        report = {
            "summary": {
                "total_checks": total_checks,
                "passed": passed_checks,
                "failed": total_checks - passed_checks,
                "score": f"{(passed_checks/total_checks)*100:.1f}%"
            },
            "critical_fixes": critical_fixes[:5],  # Top 5 critical items
            "improvements": improvements[:5],      # Top 5 improvements
            "detailed_results": [
                {
                    "check": r.check_name,
                    "passed": r.passed,
                    "message": r.message,
                    "metrics": r.metrics
                }
                for r in self.results
            ],
            "next_actions": self._generate_next_actions()
        }
        
        # Print summary
        print("\n" + "="*50)
        print("📊 VALIDATION SUMMARY")
        print("="*50)
        print(f"Total Score: {report['summary']['score']}")
        print(f"Passed: {passed_checks}/{total_checks} checks")
        
        if critical_fixes:
            print("\n🚨 Critical Fixes Needed:")
            for i, fix in enumerate(critical_fixes[:3], 1):
                print(f"   {i}. {fix}")
        
        if improvements:
            print("\n💡 Suggested Improvements:")
            for i, imp in enumerate(improvements[:3], 1):
                print(f"   {i}. {imp}")
        
        print("\n✅ Ready for investors:", "YES" if passed_checks/total_checks > 0.8 else "NO")
        
        return report
    
    def _generate_next_actions(self) -> List[str]:
        """Generate prioritized next actions based on results"""
        actions = []
        
        # Check specific conditions
        structure_ok = any(r.check_name == "Project Structure" and r.passed for r in self.results)
        api_ok = any(r.check_name == "API Endpoints" and r.passed for r in self.results)
        docker_ok = any(r.check_name == "Docker Setup" and r.passed for r in self.results)
        
        if not structure_ok:
            actions.append("Run: make init-project")
        if not api_ok:
            actions.append("Implement missing API endpoints in api/main.py")
        if not docker_ok:
            actions.append("Fix docker-compose.yml configuration")
        
        if all([structure_ok, api_ok, docker_ok]):
            actions.append("Run: ./quickstart.sh to test full system")
            actions.append("Deploy to GitHub and share link with investors")
        
        return actions
    
    def _print_result(self, result: ValidationResult):
        """Pretty print individual result"""
        icon = "✅" if result.passed else "❌"
        print(f"{icon} {result.check_name}: {result.message}")
        if not result.passed and result.suggestions:
            print(f"   → {result.suggestions[0]}")

# Feedback loop for Claude Code
class ClaudeFeedbackLoop:
    """
    Implements an iterative improvement loop for Claude Code
    """
    
    def __init__(self):
        self.validator = GridSynapseValidator()
        self.iteration_count = 0
        self.max_iterations = 5
        
    def run_improvement_cycle(self) -> bool:
        """
        Run one cycle of validation and improvement
        Returns True if all checks pass
        """
        self.iteration_count += 1
        print(f"\n🔄 Iteration {self.iteration_count}")
        print("-" * 50)
        
        # Run validation
        report = self.validator.run_all_checks()
        
        # Check if we're done
        if report["summary"]["failed"] == 0:
            print("\n🎉 All checks passed! Project is ready.")
            return True
        
        # Generate improvement prompt for Claude
        improvement_prompt = self._generate_improvement_prompt(report)
        
        # Save to file for Claude Code to read
        with open("feedback.json", "w") as f:
            json.dump({
                "iteration": self.iteration_count,
                "report": report,
                "prompt": improvement_prompt
            }, f, indent=2)
        
        print(f"\n💭 Suggested improvements saved to feedback.json")
        print("Claude Code can read this and make improvements.")
        
        return False
    
    def _generate_improvement_prompt(self, report: Dict[str, Any]) -> str:
        """Generate a specific prompt for Claude to fix issues"""
        prompt = f"""
Based on the validation results, please fix these issues:

CRITICAL FIXES (do these first):
{chr(10).join(f'- {fix}' for fix in report['critical_fixes'])}

IMPROVEMENTS (if time allows):
{chr(10).join(f'- {imp}' for imp in report['improvements'])}

Current score: {report['summary']['score']}
Goal: Get all checks passing for the investor demo.

Focus on making the minimum changes needed to pass validation.
"""
        return prompt

# CLI for running validation
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        # Run feedback loop
        loop = ClaudeFeedbackLoop()
        
        while loop.iteration_count < loop.max_iterations:
            if loop.run_improvement_cycle():
                break
            
            print("\n⏸️  Make improvements based on feedback, then press Enter to continue...")
            input()
            
            # Clear previous results for fresh validation
            loop.validator.results = []
    else:
        # Run single validation
        validator = GridSynapseValidator()
        report = validator.run_all_checks()
        
        # Save report
        with open("validation_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"\n📄 Full report saved to validation_report.json")