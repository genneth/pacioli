import json
import os
import re
import subprocess
import sys

from dotenv import load_dotenv

# Load secrets from .env to check if they are leaked in other files
load_dotenv()

def load_sensitive_patterns():
    """Loads PII patterns from an ignored JSON file."""
    patterns = []
    if os.path.exists("pii_patterns.json"):
        with open("pii_patterns.json") as f:
            try:
                patterns = json.load(f)
            except json.JSONDecodeError:
                print("Warning: pii_patterns.json is not valid JSON.")
    
    # Add dynamic patterns for secrets in .env
    secrets = [
        "GOCARDLESS_SECRET_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY"
    ]
    for key in secrets:
        val = os.getenv(key)
        if val and len(val) > 5:  # Only check meaningful strings
            # Escape for regex
            escaped_val = re.escape(val)
            patterns.append([escaped_val, f"Leaked {key} found"])
            
    return patterns

SENSITIVE_PATTERNS = load_sensitive_patterns()

def get_tracked_files():
    """Returns a list of files currently tracked by git."""
    try:
        # Use shell=True for windows to ensure git is found in PATH
        result = subprocess.run(
            "git ls-files", capture_output=True, text=True, check=True, shell=True
        )
        return result.stdout.splitlines()
    except subprocess.CalledProcessError:
        print("Error: Not a git repository or git not found.")
        return []

def check_file(file_path):
    """Scans a file for sensitive patterns."""
    issues: list[str] = []
    
    # Skip binary files and this script itself
    if file_path.endswith((".png", ".jpg", ".ico", ".pyc")) or file_path == "check_pii.py":
        return issues

    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
            for item in SENSITIVE_PATTERNS:
                if len(item) == 2:
                    pattern, description = item
                    if re.search(pattern, content, re.IGNORECASE):
                        issues.append(description)
    except Exception as e:
        print(f"Could not read {file_path}: {e}")
        
    return issues

def main():
    print("Running PII and Secrets scan on tracked files...")
    tracked_files = get_tracked_files()
    all_issues = {}

    for file_path in tracked_files:
        # Don't check the script itself or GEMINI.md (which contains the rules)
        if file_path in ["check_pii.py", "GEMINI.md"]:
            continue
            
        issues = check_file(file_path)
        if issues:
            all_issues[file_path] = issues

    if all_issues:
        print("\n[!!!] SECURITY ALERT: Potential PII or Secrets found in tracked files:")
        for file_path, issues in all_issues.items():
            print(f"  - {file_path}:")
            for issue in issues:
                print(f"    └─ {issue}")
        print("\nPlease remove these before committing.")
        sys.exit(1)
    else:
        print("\n[PASS] No sensitive patterns found in tracked files.")
        sys.exit(0)

if __name__ == "__main__":
    main()