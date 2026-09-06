import os
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

BACKUPS_DIR = Path("backups")
WEEKLY_DIR = Path("weekly_backups")

def get_target_week_range(ref_date: datetime.date = None):
    """
    Returns (monday, sunday) dates for the target week.
    If run on a Sunday, weekday() is 6, so Monday is ref_date - 6 days.
    """
    if ref_date is None:
        ref_date = datetime.now().date()
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

def compile_weekly_backup():
    if not BACKUPS_DIR.exists():
        print(f"Directory {BACKUPS_DIR} not found. Exiting.")
        return

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    
    start_date, end_date = get_target_week_range()
    print(f"Compiling backups for week: {start_date} to {end_date}")

    # Regex matches format: 2026-09-05_Saturday.json
    filename_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})_([A-Za-z]+)\.json$")
    
    weekly_files = []
    for file_path in BACKUPS_DIR.glob("*.json"):
        match = filename_pattern.match(file_path.name)
        if match:
            file_date_str = match.group(1)
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d").date()
            if start_date <= file_date <= end_date:
                weekly_files.append((file_date, file_path))

    if not weekly_files:
        print(f"No daily backup files found for the period {start_date} to {end_date}.")
        return

    # Sort files chronologically (Monday -> Sunday)
    weekly_files.sort(key=lambda x: x[0])

    compiled_payload = {
        "week_range": f"{start_date.isoformat()}_to_{end_date.isoformat()}",
        "week_number": start_date.strftime("%Y-W%W"),
        "total_days_archived": len(weekly_files),
        "total_articles": 0,
        "compiled_at": datetime.utcnow().isoformat() + "Z",
        "days_included": [],
        "editorials": []
    }

    for file_date, file_path in weekly_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                daily_data = json.load(f)

            editorials = daily_data.get("editorials", [])
            article_count = daily_data.get("total_articles", len(editorials))
            
            compiled_payload["days_included"].append(file_date.isoformat())
            compiled_payload["total_articles"] += article_count
            compiled_payload["editorials"].extend(editorials)
            
            print(f"Appended {file_path.name} ({article_count} articles)")
        except Exception as err:
            print(f"Error reading {file_path}: {err}")

    output_filename = f"{start_date.isoformat()}_to_{end_date.isoformat()}_weekly.json"
    output_path = WEEKLY_DIR / output_filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(compiled_payload, f, ensure_ascii=False, indent=2)

    print(f"\nSuccessfully compiled {compiled_payload['total_articles']} articles into {output_path}")

if __name__ == "__main__":
    compile_weekly_backup()
