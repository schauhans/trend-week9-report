import json
import os
import datetime
from pathlib import Path
from dotenv import load_dotenv
import anthropic

# Load API key from .env
load_dotenv()

# Paths
SCRIPT_DIR = Path(__file__).parent
JSON_PATH = SCRIPT_DIR / "trend_shortlist.json"
RUN_LOG_PATH = SCRIPT_DIR / "run_log.json"

MODEL = "claude-haiku-4-5-20251001"

# B1: Exact prompt the user inputs
PROMPT_TEMPLATE = (
    "You are a Dior trend briefing assistant helping client advisors (CAs) in China "
    "prepare for client interactions — cards are read during slow hours or before a "
    "shift, so they should be memorable and easy to recall on the floor.\n\n"
    "Every claim must be grounded in the provided data, translated into plain selling "
    "language a CA would naturally use — no jargon, no data-speak.\n\n"
    "OUTPUT FORMAT — follow exactly, no deviations:\n\n"
    "---\n"
    "## {trend_label} · {city} · {category}\n\n"
    "**What it is:** [Two sentences. What clients aged [TARGET_AGE_RANGE] in {city} "
    "are gravitating toward right now, and what makes it distinct from generic luxury dressing.]\n\n"
    "**Who to bring it up with:** [TARGET_AGE_RANGE] clients in {city} — [two "
    "sentences describing their mindset or lifestyle so the CA can picture them, "
    "and one signal or behaviour that tells the CA this client is ready for this conversation.]\n\n"
    "**Why it's moving:** [Two sentences. Translate the numbers into a human signal "
    "— e.g. \"Nearly 1 in 10 people who saw this saved it, which means clients are "
    "actively researching this before they buy.\" Second sentence connects the "
    "momentum directly to a {brand} opportunity.]\n\n"
    "**Open with:** \"[Two sentences the CA can use in-store or on WeChat — the "
    "first sets context or asks a natural question, the second introduces the {brand} "
    "angle. Conversational, warm, not salesy. Include a natural Chinese phrase "
    "where it fits.]\"\n\n"
    "`Confidence: {confidence}`\n\n"
    "---\n\n"
    "RULES:\n"
    "- Two sentences per section — make both count, the first should introduce the trend and its relevance "
    "and the second should land the main point and usage.\n"
    "- Never use phrases like \"this trend signals\" or \"this represents\" — name the thing directly and move on.\n"
    "- \"Why it's moving\" must reference at least one number but explain it as a human behaviour, not a statistic.\n"
    "- \"Open with\" must sound like a real person talking, not a brand deck.\n"
    "- {city_tone_rule}\n"
    "- Never invent data not present in the trend object — if a field is missing, flag it rather than fill it in.\n\n"
    "TREND DATA:\n"
    "- Trend: {trend_label}\n"
    "- City: {city}\n"
    "- Category: {category}\n"
    "- Cluster summary: {cluster_summary}\n"
    "- Post count: {post_count:,}\n"
    "- Engagement rate: {engagement_rate_pct}%\n"
    "- Week-on-week growth: {week_on_week_growth}\n"
    "- Top post example: {top_post_example}\n"
    "- Trending hashtags: {trending_hashtags}\n"
    "- Brand relevance: {brand_relevance}\n"
    "- Brand: {brand}"
)

# B3: Decision logic — rules-first
DECISION_CRITERIA = [
    "City match: trend['city'] must equal the selected store city",
    "Brand relevance: trend['brand_relevance'] must be 'high'; 'medium' accepted only if fewer than 3 high-relevance trends exist for the city",
    "Composite score: ranked by weighted sum of engagement_rate (×40), growth_pct (×30), post_count normalised (×30); top 3 selected",
]
EVIDENCE_REQUIREMENTS = [
    "Minimum post_count >= 3,000 to be considered as evidence",
    "Engagement rate >= 0.08 required; trends below this threshold are flagged LOW confidence regardless of other signals",
]
FAILURE_TYPES = {
    "MISSING_EVIDENCE": {
        "name": "FAILURE TYPE 1 — Missing Evidence",
        "trigger": "Fewer than 3 of these fields are present: post_count, engagement_rate, week_on_week_growth, cluster_summary",
        "consequence": "Card cannot make evidence-anchored claims; 'Why it's moving' would be invented. Card is skipped.",
    },
    "MISSING_CONTEXT": {
        "name": "FAILURE TYPE 2 — Missing Context",
        "trigger": "city or target_age_range is absent from the trend object",
        "consequence": "'Who to bring it up with' and city-specific tone cannot be applied — card becomes generic and unusable for a CA. Card is skipped.",
    },
    "WEAK_SIGNAL": {
        "name": "FAILURE TYPE 3 — Weak Signal",
        "trigger": "week_on_week_growth is under +10% AND engagement_rate is under 0.08",
        "consequence": "Trend has insufficient momentum to recommend this week — surfacing it risks wasting client interaction capital on something not yet proven. Card is skipped.",
    },
}

FAILURE_MODE = (
    "Three named failure types are checked before card generation. "
    "MISSING_EVIDENCE: fewer than 3 evidence fields present. "
    "MISSING_CONTEXT: city field absent. "
    "WEAK_SIGNAL: growth under +10% AND engagement under 0.08. "
    "Any failure skips the card and logs the reason. "
    "If fewer than 3 valid trends remain, the agent lowers brand_relevance threshold to include 'medium' trends."
)


def check_failures(trend):
    """
    B3: Check the three named failure types for a trend object.
    Returns a list of triggered failure type keys, or empty list if none.
    """
    failures = []

    # FAILURE TYPE 1 — Missing Evidence
    evidence_fields = ["post_count", "engagement_rate", "week_on_week_growth", "cluster_summary"]
    present = sum(1 for f in evidence_fields if trend.get(f) not in (None, "", []))
    if present < 3:
        failures.append("MISSING_EVIDENCE")

    # FAILURE TYPE 2 — Missing Context
    if not trend.get("city"):
        failures.append("MISSING_CONTEXT")

    # FAILURE TYPE 3 — Weak Signal
    if "week_on_week_growth" in trend and "engagement_rate" in trend:
        growth_str = str(trend["week_on_week_growth"]).replace("%", "").replace("+", "")
        try:
            growth_pct = int(growth_str)
        except ValueError:
            growth_pct = 0
        if growth_pct < 10 and trend["engagement_rate"] < 0.08:
            failures.append("WEAK_SIGNAL")

    return failures


def load_trends():
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"trend_shortlist.json not found at {JSON_PATH}")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_user_inputs():
    print("\n=== Dior CA Trend Brief Generator ===\n")

    brand_input = input("Brand (press Enter for Dior): ").strip()
    brand = brand_input if brand_input else "Dior"

    print("\nSelect store city:")
    print("  1 — Shanghai")
    print("  2 — Beijing")
    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            city = "Shanghai"
            break
        elif choice == "2":
            city = "Beijing"
            break
        print("  Please enter 1 or 2.")

    return brand, city


def compute_composite_score(trend):
    """Weighted composite score for ranking trends."""
    growth_pct = int(trend["week_on_week_growth"].replace("%", "").replace("+", ""))
    # Normalise post_count: treat 10,000 as max reference
    post_norm = min(trend["post_count"] / 10000, 1.0)
    return (
        trend["engagement_rate"] * 40
        + (growth_pct / 100) * 30
        + post_norm * 30
    )


def assess_confidence(trend):
    """B3: Confidence flag based on evidence requirements."""
    if trend["post_count"] < 3000:
        return "LOW"
    if trend["engagement_rate"] < 0.08:
        return "LOW"
    score = 0
    if trend["post_count"] >= 5000:
        score += 1
    if trend["engagement_rate"] >= 0.095:
        score += 1
    growth_pct = int(trend["week_on_week_growth"].replace("%", "").replace("+", ""))
    if growth_pct >= 20:
        score += 1
    if trend["brand_relevance"] == "high":
        score += 1
    if score >= 3:
        return "HIGH"
    elif score >= 2:
        return "MEDIUM"
    return "LOW"


def select_trends(trends, city, top_n=3):
    """B3: Apply decision logic — filter by city, run failure checks, rank, return top N."""
    # Step 1: filter by city
    city_trends = [t for t in trends if t["city"] == city]

    # Step 2: run failure checks — exclude any trend that triggers a failure type
    valid = []
    failed = []
    for t in city_trends:
        triggered = check_failures(t)
        if triggered:
            failed.append({"trend_id": t["trend_id"], "failures": triggered})
        else:
            valid.append(t)

    # Step 3: prefer high brand relevance among valid trends
    high_relevance = [t for t in valid if t["brand_relevance"] == "high"]
    medium_relevance = [t for t in valid if t["brand_relevance"] == "medium"]

    # Step 4: fallback to medium if not enough high-relevance trends pass
    if len(high_relevance) >= top_n:
        pool = high_relevance
        used_fallback = False
    else:
        pool = high_relevance + medium_relevance
        used_fallback = True

    # Step 5: rank by composite score, take top N
    ranked = sorted(pool, key=compute_composite_score, reverse=True)[:top_n]

    return ranked, used_fallback, failed


CITY_TONE = {
    "Beijing": "Beijing cards should feel bolder and more direct.",
    "Shanghai": "Shanghai cards should feel more understated and considered.",
}


def generate_trend_card(client, trend, brand, city):
    """B1: Build prompt and call Claude API."""
    confidence = assess_confidence(trend)
    prompt = PROMPT_TEMPLATE.format(
        brand=brand,
        city=city,
        trend_label=trend["trend_label"],
        category=trend["category"],
        cluster_summary=trend["cluster_summary"],
        post_count=trend["post_count"],
        engagement_rate_pct=round(trend["engagement_rate"] * 100, 1),
        week_on_week_growth=trend["week_on_week_growth"],
        top_post_example=trend["top_post_example"],
        trending_hashtags=", ".join(trend["trending_hashtags"]),
        brand_relevance=trend["brand_relevance"],
        confidence=confidence,
        city_tone_rule=CITY_TONE.get(city, "Tone should be refined and client-appropriate."),
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return prompt, response.content[0].text


def write_report(brand, city, week, source, selected, cards, used_fallback):
    """B4: Write city- and brand-specific markdown report."""
    output_path = SCRIPT_DIR / f"trend_cards_{brand.lower()}_{city.lower()}.md"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# CA Trend Brief — {brand} {city}\n\n")
        f.write(f"**Week:** {week}  \n")
        f.write(f"**Source:** {source}  \n")
        f.write(f"**Store:** {brand}, {city}  \n")
        f.write(f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}  \n")
        f.write(f"**Model:** {MODEL}  \n")
        if used_fallback:
            f.write(
                "\n> ⚠️ **Note:** Fewer than 3 high-relevance trends found for this city. "
                "Medium-relevance trends included and flagged LOW confidence.\n"
            )
        f.write("\n---\n\n")

        for trend, card_text in zip(selected, cards):
            confidence = assess_confidence(trend)
            f.write(f"## {trend['trend_id']}: {trend['trend_label']}\n\n")
            f.write(
                f"**Category:** {trend['category']} | "
                f"**Posts:** {trend['post_count']:,} | "
                f"**Engagement:** {trend['engagement_rate']:.1%} | "
                f"**Growth:** {trend['week_on_week_growth']} | "
                f"**Confidence:** {confidence}\n\n"
            )
            f.write(card_text.strip())
            f.write("\n\n---\n\n")

    return output_path


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set. Check your .env file.")

    client = anthropic.Anthropic(api_key=api_key)

    # B1: Get user inputs (brand + city)
    brand, city = get_user_inputs()

    # B2: Retrieve context from trend_shortlist.json
    data = load_trends()
    context = data["query_context"]
    all_trends = data["trends"]
    all_ids = [t["trend_id"] for t in all_trends]

    print(f"\nRetrieved {len(all_trends)} trends from trend_shortlist.json")
    print(f"Applying decision logic for: {brand} — {city}\n")

    # B3: Apply decision logic
    selected, used_fallback, failed_trends = select_trends(all_trends, city)

    if failed_trends:
        print(f"Excluded {len(failed_trends)} trend(s) due to failure checks:")
        for f in failed_trends:
            labels = ", ".join(FAILURE_TYPES[k]["name"] for k in f["failures"])
            print(f"  {f['trend_id']} — {labels}")
        print()

    if not selected:
        print(f"No valid trends found for city: {city}. Check your trend_shortlist.json.")
        return

    print(f"Selected {len(selected)} trends after filtering:\n")
    for t in selected:
        conf = assess_confidence(t)
        score = compute_composite_score(t)
        print(f"  {t['trend_id']}: {t['trend_label']}  [confidence={conf}, score={score:.2f}]")

    # Generate cards
    print()
    cards = []
    log_trends = []
    for i, trend in enumerate(selected, 1):
        print(f"[{i}/{len(selected)}] Generating card: {trend['trend_label']}...")
        prompt_used, card_text = generate_trend_card(client, trend, brand, city)
        confidence = assess_confidence(trend)
        cards.append(card_text)

        # B5: log per-trend trace fields
        log_trends.append({
            "trend_id": trend["trend_id"],
            "trend_label": trend["trend_label"],
            "decision_output": "SELECTED",
            "confidence": confidence,
            "composite_score": round(compute_composite_score(trend), 3),
            "evidence_used": {
                "post_count": trend["post_count"],
                "engagement_rate": trend["engagement_rate"],
                "week_on_week_growth": trend["week_on_week_growth"],
                "brand_relevance": trend["brand_relevance"],
                "top_post_example": trend["top_post_example"],
                "trending_hashtags": trend["trending_hashtags"],
            },
            "prompt_used": prompt_used,
        })

    # B4: Write markdown report
    output_path = write_report(brand, city, context["week"], context["source"], selected, cards, used_fallback)

    # B5: Save run_log.json
    high_trends = [t for t in log_trends if t["confidence"] == "HIGH"]
    next_step = (
        f"Share the {len(selected)} trend cards with the {brand} {city} CA team for review. "
        f"{len(high_trends)} card(s) are HIGH confidence and ready for client conversations. "
        f"Run log_feedback.py after team review."
    )

    run_log = {
        "run_timestamp": datetime.datetime.now().isoformat(),
        "model": MODEL,
        "brand": brand,
        "city": city,
        "week": context["week"],
        "prompt_template": PROMPT_TEMPLATE,
        "retrieved_source": "trend_shortlist.json",
        "retrieved_record_ids": all_ids,
        "decision_logic": {
            "type": "LLM-first",
            "criteria": DECISION_CRITERIA,
            "evidence_requirements": EVIDENCE_REQUIREMENTS,
            "failure_types_defined": FAILURE_TYPES,
            "failure_mode_summary": FAILURE_MODE,
            "used_fallback_to_medium_relevance": used_fallback,
            "excluded_trends": [
                {
                    "trend_id": f["trend_id"],
                    "failures": [
                        {"type": k, "definition": FAILURE_TYPES[k]}
                        for k in f["failures"]
                    ],
                }
                for f in failed_trends
            ],
        },
        "selected_trends": log_trends,
        "next_step_suggestion": next_step,
    }

    with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(run_log, f, indent=2, ensure_ascii=False)

    print(f"\nDone!")
    print(f"  Report  → {output_path.name}")
    print(f"  Run log → {RUN_LOG_PATH.name}")
    print(f"\nNext step: {next_step}")


if __name__ == "__main__":
    main()
