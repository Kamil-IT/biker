#!/usr/bin/env python3
"""Download all 449 ECC skills from GitHub repository."""

import os
import requests
import json
import time
from pathlib import Path

SKILLS_DIR = "./.claude/skills"
ECC_REPO = "affaan-m/ECC"
BRANCH = "main"
BASE_URL = f"https://raw.githubusercontent.com/{ECC_REPO}/{BRANCH}/skills"
API_URL = f"https://api.github.com/repos/{ECC_REPO}/git/trees/{BRANCH}?recursive=1"

def main():
    # Create skills directory
    Path(SKILLS_DIR).mkdir(parents=True, exist_ok=True)

    print("Fetching ECC skills list from GitHub...")
    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching skills list: {e}")
        return

    # Filter for skills (*.md files in skills/ directory)
    skill_files = [
        item["path"].split("/")[-1]
        for item in data.get("tree", [])
        if item["path"].startswith("skills/") and item["path"].endswith(".md")
    ]

    total = len(skill_files)
    print(f"Found {total} skills to download\n")

    downloaded = 0
    failed = 0
    failed_files = []

    for idx, skill_name in enumerate(sorted(skill_files), 1):
        url = f"{BASE_URL}/{skill_name}"
        output_path = os.path.join(SKILLS_DIR, skill_name)

        try:
            print(f"[{idx}/{total}] Downloading: {skill_name}...", end=" ")
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(response.text)

            downloaded += 1
            print("OK")
        except Exception as e:
            failed += 1
            failed_files.append((skill_name, str(e)))
            print(f"FAIL ({str(e)[:30]})")

        # Small delay to be respectful to GitHub
        time.sleep(0.2)

    print("\n" + "="*60)
    print("Download Complete!")
    print(f"Downloaded:  {downloaded}")
    print(f"Failed:      {failed}")

    # Count actual files
    skill_count = len([f for f in os.listdir(SKILLS_DIR) if f.endswith(".md")])
    print(f"Total skills in directory: {skill_count}")

    if failed_files:
        print("\nFailed files:")
        for name, error in failed_files[:10]:
            print(f"  - {name}: {error}")
        if len(failed_files) > 10:
            print(f"  ... and {len(failed_files) - 10} more")

if __name__ == "__main__":
    main()
