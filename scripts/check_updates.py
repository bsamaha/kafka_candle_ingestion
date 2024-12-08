import subprocess
import json
from packaging import version
import sys

def get_installed_packages():
    result = subprocess.run(
        ["pip", "list", "--format", "json"],
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)

def get_latest_versions():
    result = subprocess.run(
        ["pip", "list", "--outdated", "--format", "json"],
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)

def main():
    print("Checking for package updates...")
    
    installed = {pkg["name"]: pkg["version"] for pkg in get_installed_packages()}
    outdated = {
        pkg["name"]: {
            "current": pkg["version"],
            "latest": pkg["latest_version"]
        }
        for pkg in get_latest_versions()
    }
    
    if not outdated:
        print("All packages are up to date!")
        return
    
    print("\nOutdated packages:")
    print("-" * 60)
    print(f"{'Package':<30} {'Current':<15} {'Latest':<15}")
    print("-" * 60)
    
    for pkg, info in outdated.items():
        print(
            f"{pkg:<30} {info['current']:<15} {info['latest']:<15}"
        )
    
    print("\nTo update all packages, run:")
    print("pip-compile requirements.in --upgrade")
    print("pip-sync requirements.txt")

if __name__ == "__main__":
    main() 