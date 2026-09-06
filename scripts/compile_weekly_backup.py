import os
import re
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

BACKUPS_DIR = Path("backups")
WEEKLY_DIR = Path("weekly_backups")
IST = ZoneInfo("Asia/Kolkata")

def get_target_week_range(ref_date=None):
    """
    Returns (monday, sunday) dates for the target week based on IST.
    When running on Sunday morning IST, ref_date.weekday() == 6.
    """
    if ref_date is None:
        ref_date = datetime.now(IST).date()
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

def compile_weekly_backup():
    if not BACKUPS_DIR.exists():
        print(f"Directory {BACKUPS_DIR} not found. Exiting.")
        return

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    
    start_date, end_date = get_target_week_range()
    print(f"Compiling backups for week: {start_date} to {end_date} (IST)")

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
        print(f"No backup files found between {start_date} and {end_date}.")
        return

    weekly_files.sort(key=lambda x: x[0])

    compiled_payload = {
        "week_range": f"{start_date.isoformat()}_to_{end_date.isoformat()}",
        "week_number": start_date.strftime("%Y-W%W"),
        "total_days_archived": len(weekly_files),
        "total_articles": 0,
        "compiled_at_ist": datetime.now(IST).isoformat(),
        "days_included": [],
        "editorials": []
    }

    for file_date, file_path in weekly_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                daily_data = json.load(f)

            raw_editorials = daily_data.get("editorials", [])
            article_count = daily_data.get("total_articles", len(raw_editorials))
            
            cleaned_editorials = []
            for item in raw_editorials:
                # 1. Remove raw editorial passage text
                item.pop("passage", None)
                
                # 2. Remove analysis_summary from inside analysis
                if isinstance(item.get("analysis"), dict):
                    item["analysis"].pop("analysis_summary", None)
                    
                cleaned_editorials.append(item)

            compiled_payload["days_included"].append(file_date.isoformat())
            compiled_payload["total_articles"] += article_count
            compiled_payload["editorials"].extend(cleaned_editorials)
            
            print(f"Added {file_path.name} ({len(cleaned_editorials)} editorials)")
        except Exception as err:
            print(f"Error processing {file_path}: {err}")

    output_filename = f"{start_date.isoformat()}_to_{end_date.isoformat()}_weekly.json"
    output_path = WEEKLY_DIR / output_filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(compiled_payload, f, ensure_ascii=False, indent=2)

    print(f"\nSaved weekly consolidated backup to {output_path}")

if __name__ == "__main__":
    compile_weekly_backup()
