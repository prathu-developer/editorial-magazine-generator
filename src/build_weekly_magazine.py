import os
import re
import json
import glob
import requests
import pypdf
from pypdf import PdfReader, PdfWriter
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from wordfreq import zipf_frequency

def get_pos_rank(pos_raw):
    """Returns sort rank: Verb (1) -> Noun (2) -> Adjective (3) -> Adverb (4) -> Others (5)."""
    pos = str(pos_raw).strip().lower()
    if "adverb" in pos or "adv" in pos:
        return 4
    if "verb" in pos:
        return 1
    if "noun" in pos:
        return 2
    if "adj" in pos:
        return 3
    return 5

def _normalize_pos_family(pos_raw):
    """Normalizes part of speech into broad categories for safe matching."""
    p = str(pos_raw).strip().lower()
    # Check adverb before verb because "adverb" contains "verb"
    if "adverb" in p or "adv" in p:
        return "adv"
    if "verb" in p:
        return "verb"
    if "noun" in p:
        return "noun"
    if "adj" in p:
        return "adj"
    return "other"


def _get_base_candidates(word):
    """
    Generates plausible base stems for standard verb/noun inflections.
    Never guesses roots for irregulars or short words.
    """
    w = word.strip().lower()
    candidates = []

    # Verbs ending in -ing
    if w.endswith("ing") and len(w) > 4:
        stem = w[:-3]
        candidates.extend([stem, stem + "e"])
        if len(stem) > 1 and stem[-1] == stem[-2]:
            candidates.append(stem[:-1])

    # Verbs ending in -ed / -d
    elif w.endswith("ed") and len(w) > 3:
        stem = w[:-2]
        candidates.extend([stem, w[:-1]])
        if len(stem) > 1 and stem[-1] == stem[-2]:
            candidates.append(stem[:-1])

    # Nouns/Verbs ending in -es or -s
    elif w.endswith("es") and len(w) > 3:
        candidates.extend([w[:-2], w[:-1]])
    elif w.endswith("s") and len(w) > 2 and not w.endswith("ss"):
        candidates.append(w[:-1])

    # Suffix pairs: -ility -> -ile (e.g., volatility -> volatile; fragility -> fragile)
    elif w.endswith("ility") and len(w) > 6:
        candidates.append(w[:-5] + "ile")

    # Suffix pairs: -ance / -ence -> base verb (e.g., endurance -> endure)
    elif (w.endswith("ance") or w.endswith("ence")) and len(w) > 5:
        candidates.extend([w[:-4], w[:-4] + "e"])

    return list(dict.fromkeys([c for c in candidates if c]))


def _is_ows_derivative(core_word, ows_word):
    """Checks if an Editorial Vocab word is an obvious inflection/derivative of an OWS term."""
    c = core_word.strip().lower()
    o = ows_word.strip().lower()

    if c == o:
        return True

    if c in _get_base_candidates(o) or o in _get_base_candidates(c):
        return True

    # Suffix pairs: -ist vs -ism
    if (c.endswith("ist") and o.endswith("ism") and c[:-3] == o[:-3]) or \
       (c.endswith("ism") and o.endswith("ist") and c[:-3] == o[:-3]):
        return True

    # Suffix pairs: -ate vs -ation
    if (o.endswith("ation") and c.endswith("ate") and o[:-5] == c[:-3]) or \
       (c.endswith("ation") and o.endswith("ate") and c[:-5] == o[:-3]):
        return True

    if o.endswith("ation") and o[:-5] == c:
        return True

    return False


def categorize_vocabulary(vocab_items):
    """
    Deduplicates and filters vocabulary:
    1. Preserves OWS distinctions (e.g., Adjudication vs Adjudicator remain intact).
    2. Prioritizes Foreign Words over OWS (e.g., Impasse stays in Foreign Words, removed from OWS).
    3. Prioritizes OWS over Editorial Vocab (Mitigate, Disenfranchised, Imperialist dropped).
    4. Merges participle twins without a base verb (Inflicted vs Inflicting).
    5. Drops pure -ly adverb clones when the adjective is present (Subsequently vs Subsequent).
    6. Drops plural nouns when the singular noun is present (Preoccupations vs Preoccupation).
    7. Drops duplicate noun/adjective root clones (Volatility vs Volatile, Endurance vs Endure).
    8. Sorts each category: Letter -> POS Priority -> Alphabetical.
    """
    categorized = {
        "core_vocab": [],
        "one_word_subs": [],
        "fixed_prepositions": [],
        "phrasal_verbs": [],
        "idioms": [],
        "foreign_words": []
    }
    seen_words = {cat: set() for cat in categorized}

    # Step 1: Initial bucket routing
    raw_core_vocab = []
    for item in vocab_items:
        cat = str(item.get("category", "")).strip().lower()
        if "one-word" in cat or "one word" in cat:
            target = "one_word_subs"
        elif "preposition" in cat:
            target = "fixed_prepositions"
        elif "phrasal" in cat:
            target = "phrasal_verbs"
        elif "idiom" in cat:
            target = "idioms"
        elif "foreign" in cat:
            target = "foreign_words"
        else:
            target = "core_vocab"

        word_key = str(item.get("word_or_phrase", "")).strip().lower()
        if not word_key:
            continue

        if target == "core_vocab":
            if word_key not in seen_words["core_vocab"]:
                seen_words["core_vocab"].add(word_key)
                raw_core_vocab.append(item)
        else:
            if word_key not in seen_words[target]:
                seen_words[target].add(word_key)
                categorized[target].append(item)

    # Step 2: Cross-Category Exclusion
    # 2a. Filter OWS against Foreign Words (keep loanwords like 'Impasse' exclusively in Foreign Words)
    foreign_set = {str(x.get("word_or_phrase", "")).strip().lower() for x in categorized["foreign_words"]}
    categorized["one_word_subs"] = [
        item for item in categorized["one_word_subs"]
        if str(item.get("word_or_phrase", "")).strip().lower() not in foreign_set
    ]

    # 2b. Filter Editorial Vocab against OWS and other specialized sections
    ows_words = [str(item.get("word_or_phrase", "")).strip().lower() for item in categorized["one_word_subs"]]
    other_claimed = set()
    for cat in ["foreign_words", "fixed_prepositions", "phrasal_verbs", "idioms"]:
        for item in categorized[cat]:
            other_claimed.add(str(item.get("word_or_phrase", "")).strip().lower())

    filtered_core = []
    for item in raw_core_vocab:
        w = str(item.get("word_or_phrase", "")).strip().lower()
        if w in other_claimed:
            continue
        if any(_is_ows_derivative(w, ows_w) for ows_w in ows_words):
            continue
        filtered_core.append(item)

    # Step 3: Editorial Vocab Refinement
    core_word_pos_map = {}
    for item in filtered_core:
        w = str(item.get("word_or_phrase", "")).strip().lower()
        pos_family = _normalize_pos_family(item.get("part_of_speech", ""))
        core_word_pos_map.setdefault(w, set()).add(pos_family)

    seen_participle_stems = set()
    final_core = []

    for item in filtered_core:
        word = str(item.get("word_or_phrase", "")).strip().lower()
        pos_family = _normalize_pos_family(item.get("part_of_speech", ""))

        # Rule: Drop pure -ly adverb clone if base adjective is present
        if pos_family == "adv" and word.endswith("ly") and len(word) > 4:
            base_adj = word[:-2]
            if base_adj in core_word_pos_map and "adj" in core_word_pos_map[base_adj]:
                continue

        candidates = _get_base_candidates(word)

        # Drop inflected variants if the base form exists in the list
        if any(base in core_word_pos_map for base in candidates):
            # Drop plural noun if singular noun exists (e.g., preoccupations -> preoccupation)
            if pos_family == "noun" and any(base in core_word_pos_map and "noun" in core_word_pos_map[base] for base in candidates):
                continue
            # Drop noun if adjective/verb root exists (e.g., volatility -> volatile; endurance -> endure)
            if pos_family == "noun" and any(base in core_word_pos_map and "adj" in core_word_pos_map[base] for base in candidates):
                continue
            if pos_family == "noun" and any(base in core_word_pos_map and "verb" in core_word_pos_map[base] for base in candidates):
                continue
            # Drop conjugated verb if base verb exists (e.g., quashed -> quash)
            if pos_family == "verb" and any(base in core_word_pos_map and "verb" in core_word_pos_map[base] for base in candidates):
                continue

        # Merge participle twins when base verb is missing (e.g., Inflicting dropped when Inflicted is seen)
        if pos_family == "verb" and (word.endswith("ed") or word.endswith("ing")):
            primary_stem = candidates[0] if candidates else None
            if primary_stem:
                if primary_stem in seen_participle_stems:
                    continue
                seen_participle_stems.add(primary_stem)

        final_core.append(item)

    categorized["core_vocab"] = final_core

    # Step 4: Sort each category: True Dictionary Alphabetical Order (A-Z)
    for cat in categorized:
        categorized[cat].sort(key=lambda x: (
            str(x.get("word_or_phrase", "")).strip().lower(),
            get_pos_rank(x.get("part_of_speech", ""))
        ))

    return categorized

# ----------------------------------------------------------------------
# DYNAMIC VOCABULARY ELIMINATION & AUDIT ENGINE (ZERO HARDCODING)
# ----------------------------------------------------------------------

# Standard Academic Word List (AWL) - 570 universal academic word families
AWL_SHIELD = {
    "abandon", "abstract", "academy", "access", "accommodate", "accompany", "accumulate",
    "accurate", "achieve", "acknowledge", "acquire", "adapt", "adequate", "adjacent",
    "adjust", "administrate", "advocate", "aggregate", "allocate", "alter", "alternative",
    "ambiguous", "amend", "analogy", "analyse", "anticipate", "apparent", "append",
    "appreciate", "approach", "appropriate", "approximate", "arbitrary", "aspect", "assemble",
    "assess", "assign", "assist", "assume", "assure", "attach", "attain", "attitude",
    "attribute", "author", "authority", "automate", "available", "aware", "behalf", "benefit",
    "bias", "bond", "brief", "bulk", "capable", "capacity", "category", "cease", "challenge",
    "channel", "circumstance", "cite", "civil", "clarify", "classic", "clause", "code",
    "coherent", "coincide", "collapse", "colleague", "commence", "comment", "commission",
    "commit", "commodity", "compatible", "compensate", "compile", "complement", "complex",
    "component", "compound", "comprehensive", "comprise", "compute", "conceive", "concentrate",
    "concept", "conclude", "concurrent", "conduct", "confer", "confine", "confirm", "conform",
    "consent", "consequent", "considerable", "consist", "constitute", "constrain", "construct",
    "consult", "consume", "contact", "contemporary", "context", "contract", "contradict",
    "contrary", "contrast", "contribute", "controversy", "convene", "converse", "convert",
    "convince", "cooperate", "coordinate", "core", "corporate", "correspond", "crucial",
    "currency", "cycle", "debate", "decade", "decline", "deduce", "define", "definite",
    "demonstrate", "denote", "deny", "depress", "derive", "design", "despite", "detect",
    "deviate", "device", "devote", "differentiate", "dimension", "diminish", "discrete",
    "discriminate", "displace", "display", "dispose", "distinct", "distort", "distribute",
    "diverse", "document", "domain", "domestic", "dominate", "draft", "duration", "dynamic",
    "economy", "eliminate", "emerge", "emphasis", "empirical", "enable", "encounter", "energy",
    "enforce", "enhance", "enormous", "ensure", "entity", "environment", "equate", "equip",
    "equivalent", "erode", "error", "establish", "estate", "estimate", "ethic", "ethnic",
    "evaluate", "eventual", "evident", "evolve", "exceed", "exclude", "exhibit", "expand",
    "expert", "explicit", "exploit", "export", "expose", "external", "extract", "facilitate",
    "factor", "feature", "federal", "fee", "file", "final", "finance", "finite", "flexible",
    "fluctuate", "focus", "format", "formula", "forthcoming", "foundation", "framework",
    "function", "fund", "fundamental", "furthermore", "gender", "generate", "generation",
    "globe", "goal", "grade", "grant", "guarantee", "guideline", "hence", "hierarchy",
    "highlight", "hypothesis", "identical", "identify", "ideology", "ignorant", "illustrate",
    "image", "immigrate", "impact", "implement", "implicate", "implicit", "imply", "impose",
    "incentive", "incidence", "incline", "income", "incorporate", "index", "indicate",
    "individual", "induce", "inevitable", "infer", "infrastructure", "inherent", "inhibit",
    "initial", "initiate", "injure", "innovate", "input", "insert", "insight", "inspect",
    "instance", "institute", "instruct", "integral", "integrate", "integrity", "intelligence",
    "intense", "interact", "intermediate", "internal", "interpret", "interval", "intervene",
    "intrinsic", "invest", "investigate", "invoke", "involve", "isolate", "issue", "item",
    "journal", "justify", "label", "layer", "lecture", "legal", "legislate", "levy",
    "liberal", "licence", "likewise", "link", "locate", "logic", "maintain", "major",
    "manipulate", "manual", "margin", "mature", "maximise", "mechanism", "media", "mediate",
    "medical", "medium", "mental", "method", "migrate", "military", "minimal", "minimise",
    "minimum", "ministry", "minor", "mode", "modify", "monitor", "motive", "mutual", "negate",
    "network", "neutral", "nevertheless", "nonetheless", "norm", "normal", "notion",
    "notwithstanding", "nuclear", "objective", "obtain", "obvious", "occupy", "occur", "odd",
    "offset", "ongoing", "option", "orient", "outcome", "output", "overall", "overlap",
    "overseas", "panel", "paradigm", "paragraph", "parallel", "parameter", "participate",
    "partner", "passive", "perceive", "percent", "period", "persist", "perspective", "phase",
    "phenomenon", "philosophy", "physical", "policy", "portion", "pose", "positive",
    "potential", "practitioner", "precede", "precise", "predict", "predominant", "preliminary",
    "presume", "previous", "primary", "prime", "principal", "principle", "prior", "priority",
    "proceed", "process", "professional", "prohibit", "project", "promote", "proportion",
    "prospect", "protocol", "psychology", "publication", "publish", "purchase", "pursue",
    "qualitative", "quote", "radical", "random", "range", "ratio", "rational", "react",
    "recover", "refine", "regime", "region", "register", "regulate", "reinforce", "reject",
    "relax", "release", "relevant", "reluctance", "rely", "remove", "require", "research",
    "reside", "resolve", "resource", "respond", "restore", "restrain", "restrict", "retain",
    "reveal", "revenue", "reverse", "revise", "revolution", "rigid", "role", "route",
    "scenario", "schedule", "scheme", "scope", "section", "sector", "secure", "seek",
    "select", "sequence", "series", "shift", "significant", "similar", "simulate", "site",
    "so-called", "sole", "somewhat", "source", "specific", "specify", "sphere", "stable",
    "statistic", "status", "straightforward", "strategy", "stress", "structure", "style",
    "submit", "subordinate", "subsequent", "subsidy", "substitute", "successor", "sufficient",
    "sum", "summary", "supplement", "survey", "survive", "suspend", "sustain", "symbol",
    "target", "task", "team", "technical", "technique", "technology", "temporary", "tense",
    "terminate", "text", "theme", "theory", "thereby", "thesis", "topic", "trace", "tradition",
    "transfer", "transform", "transit", "transmit", "transport", "trend", "trigger",
    "ultimate", "undergo", "underlie", "undertake", "uniform", "unify", "unique", "utilise",
    "valid", "vary", "vehicle", "version", "via", "violate", "virtual", "visible", "vision",
    "visual", "volume", "voluntary", "welfare", "whereas", "whereby", "widespread"
}

# Threshold: Words with Zipf >= 5.00 are everyday conversational English (>100 per million)
ELEMENTARY_THRESHOLD = 4.20

def _get_phrase_word_scores(phrase):
    """Extracts alphabetic tokens and returns list of (word, zipf_score) tuples."""
    tokens = [w for w in re.findall(r"[a-zA-Z]+", phrase.lower()) if len(w) > 1]
    return [(w, round(zipf_frequency(w, "en"), 2)) for w in tokens]

def audit_and_filter_vocabulary(universal_vocab, audit_json_path):
    """
    Dynamically filters vocabulary without hardcoded word lists:
    1. Categories 'one_word_subs' and 'foreign_words' always kept.
    2. Single words checked against Academic Word List (AWL) and elementary threshold.
    3. Multi-word phrases checked for bottleneck word rarity: if every word is elementary (>= 5.00), it is eliminated.
    Saves an audit JSON sorted in decreasing order of Zipf score (easiest to rarest).
    """
    pruned_vocab = {cat: [] for cat in universal_vocab}
    kept_records = []
    eliminated_records = []

    for cat_key, items in universal_vocab.items():
        for item in items:
            term = str(item.get("word_or_phrase", "")).strip()
            term_lower = term.lower()
            word_scores = _get_phrase_word_scores(term_lower)

            # Assign score: for single word it's its own score; for phrase it's the score of its rarest word
            if len(word_scores) == 1:
                effective_score = word_scores[0][1]
            elif len(word_scores) > 1:
                effective_score = min(score for _, score in word_scores)
            else:
                effective_score = round(zipf_frequency(term_lower, "en"), 2)

            record = {
                "term": term,
                "category": cat_key,
                "part_of_speech": item.get("part_of_speech", ""),
                "effective_score": effective_score,
                "word_breakdown": {w: s for w, s in word_scores} if len(word_scores) > 1 else {},
                "reason": ""
            }

            # Rule 1: Always protect exam-specific categories (OWS & Foreign Words)
            if cat_key in ["one_word_subs", "foreign_words"]:
                record["reason"] = "Retained: Exam-critical category immunity"
                kept_records.append(record)
                pruned_vocab[cat_key].append(item)
                continue

            # Rule 2: Multi-word phrase dynamic evaluation (Prepositions, Phrasals, Idioms)
            if len(word_scores) > 1:
                # If every single word in the phrase is common conversational English (all >= 5.00)
                if all(score >= ELEMENTARY_THRESHOLD for _, score in word_scores):
                    record["reason"] = f"Eliminated: Trivial phrase (all words elementary, Zipf >= {ELEMENTARY_THRESHOLD})"
                    eliminated_records.append(record)
                    continue
                else:
                    rarest_word = min(word_scores, key=lambda x: x[1])[0]
                    record["reason"] = f"Retained: Contains target/rare lexicon '{rarest_word}' (Zipf {effective_score})"
                    kept_records.append(record)
                    pruned_vocab[cat_key].append(item)
                    continue

            # Rule 3: Single Word Academic Word List (AWL) Shield
            candidates = _get_base_candidates(term_lower)
            if term_lower in AWL_SHIELD or any(base in AWL_SHIELD for base in candidates):
                record["reason"] = "Retained: Academic Word List (AWL) immunity"
                kept_records.append(record)
                pruned_vocab[cat_key].append(item)
                continue

            # Rule 4: Single Word Elementary Floor Cut
            if effective_score >= ELEMENTARY_THRESHOLD:
                record["reason"] = f"Eliminated: Elementary frequency floor (Zipf {effective_score} >= {ELEMENTARY_THRESHOLD})"
                eliminated_records.append(record)
                continue

            # Default: Retain high-yield single word
            record["reason"] = f"Retained: High-yield target vocabulary (Zipf {effective_score})"
            kept_records.append(record)
            pruned_vocab[cat_key].append(item)

    # Sort both lists in decreasing order of effective_score (highest/easiest to lowest/rarest)
    kept_records.sort(key=lambda x: x["effective_score"], reverse=True)
    eliminated_records.sort(key=lambda x: x["effective_score"], reverse=True)

    audit_payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_original": len(kept_records) + len(eliminated_records),
            "total_retained": len(kept_records),
            "total_eliminated": len(eliminated_records),
            "elementary_threshold": ELEMENTARY_THRESHOLD,
            "sorting_order": "Decreasing by effective_score (easiest/most common to rarest)"
        },
        "eliminated_words": eliminated_records,
        "retained_words": kept_records
    }

    with open(audit_json_path, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, ensure_ascii=False, indent=2)

    print(f"📋 Audit report saved: {audit_json_path}")
    print(f"✂️ Pruned {len(eliminated_records)} entries. Retained {len(kept_records)} high-yield items.")

    return pruned_vocab

def send_to_telegram(pdf_path, date_range_formatted, total_articles, total_words, newspapers_covered, universal_vocab):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram BOT_TOKEN or ADMIN_CHAT_ID missing. Skipping Telegram upload.")
        return

    # Category counts breakdown
    core_count = len(universal_vocab.get("core_vocab", []))
    ows_count = len(universal_vocab.get("one_word_subs", []))
    prep_count = len(universal_vocab.get("fixed_prepositions", []))
    phr_count = len(universal_vocab.get("phrasal_verbs", []))
    idm_count = len(universal_vocab.get("idioms", []))
    foreign_count = len(universal_vocab.get("foreign_words", []))

    caption = (
        f"📚 <b>Ez Editorialś Weekly Vocab Lab</b>\n"
        f"🗓 <b>Edition:</b> {date_range_formatted}\n"
        f"🗞 <b>Newspapers Covered:</b> {newspapers_covered}\n\n"
        f"📊 <b>Compilation Overview:</b>\n"
        f"• <b>Total Editorials:</b> {total_articles} Articles\n"
        f"• <b>Total High-Yield Lexicons:</b> {total_words} Words\n\n"
        f"🗂 <b>What's Inside:</b>\n"
        f"📖 <b>Editorial Vocab:</b> {core_count} words (with Hindi & Connotations)\n"
        f"📝 <b>One-Word Substitutions:</b> {ows_count} terms\n"
        f"🔗 <b>Fixed Prepositions:</b> {prep_count} rules\n"
        f"⚡ <b>Phrasal Verbs:</b> {phr_count} phrases\n"
        f"💡 <b>Idioms & Expressions:</b> {idm_count} idioms\n"
    )

    if foreign_count > 0:
        caption += f"🌐 <b>Foreign Words & Phrases:</b> {foreign_count} terms\n"

    caption += (
        f"\n🎯 <i>Curated for SSC CGL, Banking, UPSC & State PCS aspirants. "
        f"Includes synonyms/antonyms & complete editorial index on Page 03.</i>"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    filename = os.path.basename(pdf_path)

    print(f"📤 Uploading {filename} to Telegram...")
    with open(pdf_path, "rb") as doc:
        files = {"document": (filename, doc, "application/pdf")}
        payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML"
        }
        res = requests.post(url, data=payload, files=files)
        
    if res.status_code == 200:
        print("🚀 Successfully sent Weekly Compilation to Telegram!")
    else:
        print(f"❌ Telegram API Error ({res.status_code}): {res.text}")

def compile_weekly_magazine():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backups_dir = os.path.join(base_dir, "backups")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Determine the week window with support for manual overrides and Sunday runs
    ist = timezone(timedelta(hours=5, minutes=30))
    target_env = os.getenv("TARGET_DATE")
    
    if target_env:
        ref_date = datetime.strptime(target_env.strip(), "%Y-%m-%d").date()
    else:
        ref_date = datetime.now(ist).date()
        # If triggered on Sunday, pull the Monday-Saturday week that just ended
        if ref_date.weekday() == 6:
            ref_date -= timedelta(days=1)

    current_monday = ref_date - timedelta(days=ref_date.weekday())
    current_saturday = current_monday + timedelta(days=5)

    all_files = sorted(glob.glob(os.path.join(backups_dir, "*.json")))
    json_files = []

    for file_path in all_files:
        filename = os.path.basename(file_path)
        try:
            # Extracts 'YYYY-MM-DD' from 'YYYY-MM-DD_Weekday.json'
            date_part = filename.split("_")[0]
            file_date = datetime.strptime(date_part, "%Y-%m-%d").date()

            # Include only files belonging to the ongoing week
            if current_monday <= file_date <= current_saturday:
                json_files.append(file_path)
        except (ValueError, IndexError):
            continue

    if not json_files:
        print(f"⚠️ No JSON files found for the current week ({current_monday} to {current_saturday}) in: {backups_dir}")
        return

    print(f"📂 Loaded {len(json_files)} files for week {current_monday} to {current_saturday}:")
    for f in json_files:
        print(f"   • {os.path.basename(f)}")

    aggregated_editorials = []
    all_raw_dates = []

    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                daily_data = json.load(f)
                aggregated_editorials.extend(daily_data.get("editorials", []))
                
                # Extract date from json metadata or filename
                scraped_date = daily_data.get("date_scraped")
                if scraped_date:
                    all_raw_dates.append(scraped_date)
            except json.JSONDecodeError:
                print(f"⚠️ Skipping corrupted JSON: {file_path}")

    # Calculate date range from Monday to Saturday
    all_raw_dates = sorted(list(set(all_raw_dates)))
    if all_raw_dates:
        start_dt = datetime.strptime(all_raw_dates[0], "%Y-%m-%d")
        end_dt = datetime.strptime(all_raw_dates[-1], "%Y-%m-%d")
        date_range_formatted = f"{start_dt.strftime('%d %b')} – {end_dt.strftime('%d %b %Y')}"
    else:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        date_range_formatted = now.strftime("%d %b %Y")

    # Collect unique newspapers and build TOC index entries
    newspapers = set()
    index_entries = []
    editorial_titles = []
    all_vocab_items = []

    for art in aggregated_editorials:
        title = art.get("title", "Untitled Editorial")
        np = art.get("newspaper", "Editorial")
        editorial_titles.append(title)
        newspapers.add(np)

        # Ingest vocabulary from ALL editorials across the entire week
        all_vocab_items.extend(art.get("editorial_vocabulary", []))

        index_entries.append({
            "title": title,
            "newspaper": np,
            "timestamp": art.get("timestamp", "")
        })

    # Limit only Page 3's Index cards to 25 so Page 3 never overflows
    index_entries = index_entries[:25]

    # Universal Categorization across all 25 articles
    raw_universal_vocab = categorize_vocabulary(all_vocab_items)

    # Filter baseline words and write audit JSON
    ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    audit_filename = f"vocab_audit_{ist_time.strftime('%Y-%m-%d')}.json"
    audit_json_path = os.path.join(output_dir, audit_filename)
    universal_vocab = audit_and_filter_vocabulary(raw_universal_vocab, audit_json_path)

    newspapers_covered = " & ".join(sorted(newspapers)) if newspapers else "National Dailies"

    total_unique_words = sum(len(items) for items in universal_vocab.values())

    # Prepare Template Engine
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("weekly_template.html")

    rendered_html_path = os.path.join(build_dir, "weekly_magazine.html")
    pass1_pdf_path = os.path.join(build_dir, "temp_pass1.pdf")
    base_pdf_path = os.path.join(build_dir, "temp_base.pdf")
    overlay_pdf_path = os.path.join(build_dir, "temp_overlay.pdf")

    ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    pdf_filename = f"Weekly_Compilation_{ist_time.strftime('%Y-%m-%d')}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)

    # Initial fallback TOC page numbers (inner pages start at 4)
    toc_pages = {k: 4 for k in universal_vocab.keys()}

    # CRITICAL: Removed '--single-process' which causes Chromium to crash on Linux runners
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu"
        ])
        page = browser.new_page()

        # -------------------------------------------------------------
        # PASS 1: Render draft HTML & detect start page for each section
        # -------------------------------------------------------------
        with open(rendered_html_path, "w", encoding="utf-8") as f:
            f.write(template.render(
                date_range_formatted=date_range_formatted,
                total_articles=len(aggregated_editorials),
                total_words=total_unique_words,
                newspapers_covered=newspapers_covered,
                index_entries=index_entries,
                universal_vocab=universal_vocab,
                toc_pages=toc_pages
            ))

        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(
            path=pass1_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )

        # Scan PDF for Category Headers (Search ONLY page 4 onwards to avoid Page 2 TOC false matches)
        reader1 = PdfReader(pass1_pdf_path)
        category_markers = [
            ("core_vocab", "EDITORIAL VOCABULARY"),
            ("one_word_subs", "ONE-WORD SUBSTITUTIONS"),
            ("fixed_prepositions", "FIXED PREPOSITIONS"),
            ("phrasal_verbs", "PHRASAL VERBS"),
            ("idioms", "IDIOMS & PHRASES"),
            ("foreign_words", "FOREIGN WORDS & PHRASES")
        ]

        detected_pages = {}
        for page_idx, p_obj in enumerate(reader1.pages, start=1):
            if page_idx < 4:
                continue
            text = (p_obj.extract_text() or "").upper()
            for cat_key, marker in category_markers:
                if cat_key not in detected_pages and marker in text:
                    detected_pages[cat_key] = page_idx

        toc_pages.update(detected_pages)

        # -------------------------------------------------------------
        # PASS 2: Render final HTML with exact TOC numbers
        # -------------------------------------------------------------
        with open(rendered_html_path, "w", encoding="utf-8") as f:
            f.write(template.render(
                date_range_formatted=date_range_formatted,
                total_articles=len(aggregated_editorials),
                total_words=total_unique_words,
                newspapers_covered=newspapers_covered,
                index_entries=index_entries,
                universal_vocab=universal_vocab,
                toc_pages=toc_pages
            ))

        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(
            path=base_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )

        # -------------------------------------------------------------
        # PASS 3: Generate Dynamic Footer Page Numbers for inner pages
        # -------------------------------------------------------------
        final_reader = PdfReader(base_pdf_path)
        total_pages = len(final_reader.pages)

        overlay_pages_html = []
        for i in range(1, total_pages + 1):
            if 4 <= i < total_pages:
                overlay_pages_html.append(f'<div class="overlay-page"><div class="footer-page-badge">Page {i:02d}</div></div>')
            else:
                overlay_pages_html.append('<div class="overlay-page"></div>')

        # Drop the external @import; use system sans-serif stack to prevent font bloat
        overlay_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <style>
          @page {{ size: 210mm 297mm; margin: 0; }}
          * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-print-color-adjust: exact !important; }}
          body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Montserrat", sans-serif; }}
          .overlay-page {{ width: 210mm; height: 297mm; position: relative; }}
          .overlay-page:not(:last-child) {{ page-break-after: always; break-after: page; }}
          .footer-page-badge {{
            position: absolute;
            bottom: 1.8mm;
            right: 12mm;
            font-size: 8px;
            font-weight: 800;
            color: #ffffff;
            background: #0f2b48;
            padding: 2px 8px;
            border-radius: 4px;
            letter-spacing: 0.3px;
          }}
        </style>
        </head>
        <body>
          {''.join(overlay_pages_html)}
        </body>
        </html>
        """

        page.set_content(overlay_html, wait_until="load")
        page.pdf(
            path=overlay_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    # -------------------------------------------------------------
    # MERGE: Stamp overlay badges & Lossless Compression
    # -------------------------------------------------------------
    overlay_reader = PdfReader(overlay_pdf_path)
    writer = PdfWriter()

    for idx, pdf_page in enumerate(final_reader.pages):
        if 3 <= idx < len(final_reader.pages) - 1:
            if idx < len(overlay_reader.pages):
                pdf_page.merge_page(overlay_reader.pages[idx])
        writer.add_page(pdf_page)

    # 1. Deduplicate identical fonts, graphics states, and forms across all merged pages
    writer.compress_identical_objects()

    # 2. Apply lossless zlib Flate compression to all content streams
    for page in writer.pages:
        page.compress_content_streams()

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    # Cleanup temporary PDFs
    for tmp in [pass1_pdf_path, base_pdf_path, overlay_pdf_path]:
        if os.path.exists(tmp):
            os.remove(tmp)

    print(f"✅ Generated Weekly Magazine with TOC & Page Numbers: {output_pdf_path}")
    send_to_telegram(
        pdf_path=output_pdf_path,
        date_range_formatted=date_range_formatted,
        total_articles=len(aggregated_editorials),
        total_words=total_unique_words,
        newspapers_covered=newspapers_covered,
        universal_vocab=universal_vocab
    )

if __name__ == "__main__":
    compile_weekly_magazine()
