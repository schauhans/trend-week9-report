import json
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RUN_LOG_PATH = SCRIPT_DIR / "run_log.json"
FEEDBACK_LOG_PATH = SCRIPT_DIR / "feedback_log.json"


def load_run_log():
    if not RUN_LOG_PATH.exists():
        print("No run_log.json found. Run agent.py first.")
        return None
    with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_feedback_log():
    if FEEDBACK_LOG_PATH.exists():
        with open(FEEDBACK_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def get_score(prompt, min_val=1, max_val=5):
    while True:
        try:
            val = int(input(prompt))
            if min_val <= val <= max_val:
                return val
            print(f"  Please enter a number between {min_val} and {max_val}.")
        except ValueError:
            print("  Invalid input. Please enter a number.")


def main():
    run_log = load_run_log()
    if not run_log:
        return

    feedback_log = load_feedback_log()

    print("\n=== Feedback Logger ===")
    print(f"Run:    {run_log['run_timestamp'][:16]}")
    print(f"Brand:  {run_log['brand']}  |  Week: {run_log['week']}")
    print(f"Trends: {len(run_log['trends_processed'])}\n")

    session = {
        "session_id": datetime.datetime.now().isoformat(),
        "run_timestamp": run_log["run_timestamp"],
        "brand": run_log["brand"],
        "week": run_log["week"],
        "overall": {},
        "per_trend": [],
    }

    # Overall feedback
    print("--- Overall Run ---")
    session["overall"]["usefulness"] = get_score("Overall usefulness (1-5): ")
    session["overall"]["trust"] = get_score("Overall trust in outputs (1-5): ")
    session["overall"]["comment"] = input("Comment (Enter to skip): ").strip()

    # Optional per-trend feedback
    do_per = input("\nEnter feedback per trend? (y/n): ").strip().lower() == "y"
    if do_per:
        for trend in run_log["trends_processed"]:
            print(f"\n--- {trend['trend_id']}: {trend['trend_label']} ---")
            print(f"  Confidence: {trend['confidence_flag']}  |  Growth: {trend['week_on_week_growth']}")
            usefulness = get_score("  Usefulness (1-5): ")
            trust = get_score("  Trust (1-5): ")
            comment = input("  Comment (Enter to skip): ").strip()
            session["per_trend"].append(
                {
                    "trend_id": trend["trend_id"],
                    "trend_label": trend["trend_label"],
                    "usefulness": usefulness,
                    "trust": trust,
                    "comment": comment,
                }
            )

    feedback_log.append(session)

    with open(FEEDBACK_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(feedback_log, f, indent=2, ensure_ascii=False)

    print(f"\nFeedback saved to {FEEDBACK_LOG_PATH.name}")


if __name__ == "__main__":
    main()
