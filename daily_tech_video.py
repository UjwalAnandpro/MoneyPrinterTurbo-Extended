import os
import sys
import json
import time
import socket
import datetime
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from duckduckgo_search import DDGS
except ImportError:
    try:
        from ddgs import DDGS
    except ImportError:
        DDGS = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Set up project root in python path
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

from loguru import logger
from app.config import config
from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
from app.services import task, llm, gdrive
from app.utils import utils

STORAGE_DIR = CURRENT_DIR / "storage"
RUNS_LOG_FILE = STORAGE_DIR / "daily_runs.json"
STATE_FILE = STORAGE_DIR / "daily_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading daily_state.json: {e}")
    return {}


def save_state(state: dict):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    try:
        from app.services import status_service
        status_service.save_status_files()
    except Exception:
        pass



def wait_for_internet(timeout_minutes=15, check_interval_seconds=10):
    """Wait until an active internet connection is detected."""
    logger.info("Checking internet connection...")
    start_time = time.time()
    max_time = timeout_minutes * 60

    while time.time() - start_time < max_time:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            logger.success("Internet connection confirmed.")
            return True
        except (socket.timeout, OSError):
            logger.warning(f"No internet connection yet. Retrying in {check_interval_seconds}s...")
            time.sleep(check_interval_seconds)

    logger.error("Internet connection timeout exceeded.")
    return False


def has_already_run_today():
    """Check if the video generator already ran successfully today for both languages."""
    if not RUNS_LOG_FILE.exists():
        return False

    try:
        with open(RUNS_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            today_str = datetime.date.today().isoformat()
            if data.get("last_run_date") == today_str and data.get("status") == "success":
                # Check if both videos completed
                completed_langs = data.get("completed_languages", [])
                if "english" in completed_langs and "hindi" in completed_langs:
                    return True
    except Exception as e:
        logger.warning(f"Error reading runs log file: {e}")

    return False


def record_run_result(status: str, results: list):
    """Save the run result to avoid duplicate execution on the same day."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.date.today().isoformat()
    now_str = datetime.datetime.now().isoformat()

    history = []
    if RUNS_LOG_FILE.exists():
        try:
            with open(RUNS_LOG_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                history = old_data.get("history", [])
        except Exception:
            pass

    completed_langs = [r.get("language") for r in results if r.get("status") == "success"]

    history.append({
        "timestamp": now_str,
        "date": today_str,
        "status": status,
        "completed_languages": completed_langs,
        "results": results,
    })

    data = {
        "last_run_date": today_str,
        "last_run_timestamp": now_str,
        "status": status,
        "completed_languages": completed_langs,
        "history": history[-30:],
    }

    with open(RUNS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_past_topics() -> list[str]:
    """Retrieve all topics used in the past 30 days from daily_runs.json to prevent duplicate videos."""
    past_topics = []
    if RUNS_LOG_FILE.exists():
        try:
            with open(RUNS_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                history = data.get("history", [])
                for run in history:
                    for res in run.get("results", []):
                        t = res.get("topic", "").strip()
                        if t and t not in past_topics:
                            past_topics.append(t)
        except Exception as e:
            logger.warning(f"Error reading past topics from runs log: {e}")
    return past_topics


def is_topic_duplicate(title: str, past_topics: list[str]) -> bool:
    """Check if a headline is too similar to any previously covered topics."""
    if not title or not past_topics:
        return False
    title_norm = title.lower().strip()
    t_words = set(re.findall(r'[\w]{4,}', title_norm))
    if not t_words:
        return False
    for past in past_topics:
        past_norm = past.lower().strip()
        if past_norm == title_norm:
            return True
        p_words = set(re.findall(r'[\w]{4,}', past_norm))
        if len(p_words) >= 3:
            overlap = len(t_words & p_words) / min(len(t_words), len(p_words))
            if overlap >= 0.7:
                return True
    return False


def fetch_live_24h_trending_news() -> list[dict]:
    """Fetch top trending and viral news stories published in the last 24 hours across all categories."""
    past_topics = get_past_topics()
    news_items = []

    # 1. DuckDuckGo News (Trending and viral stories)
    if DDGS:
        search_queries = [
            "top trending news today",
            "viral breaking news and discoveries today"
        ]
        for query in search_queries:
            try:
                ddgs = DDGS(timeout=10)
                results = list(ddgs.news(query, timelimit="d", max_results=6))
                for r in results:
                    t = r.get("title", "").strip()
                    b = r.get("body", "").strip()
                    if t and len(t) > 15 and not is_topic_duplicate(t, past_topics) and not any(n["title"].lower() == t.lower() for n in news_items):
                        news_items.append({"title": t, "summary": b, "source": "DuckDuckGo"})
            except Exception as e:
                logger.warning(f"DuckDuckGo trending search notice ({query}): {e}")

    # 2. Google News 24-Hour Top Stories & Major Categories RSS Feeds
    rss_urls = [
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en"
    ]
    for url in rss_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
                for item in root.findall(".//item")[:6]:
                    title_elem = item.find("title")
                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    if " - " in title:
                        title = title.rsplit(" - ", 1)[0].strip()
                    if title and not is_topic_duplicate(title, past_topics) and not any(n["title"].lower() == title.lower() for n in news_items):
                        news_items.append({"title": title, "summary": "", "source": "Google News 24h"})
        except Exception as e:
            logger.warning(f"Google News RSS fetch notice: {e}")

    return news_items


# Backward compatibility alias
fetch_live_24h_tech_news = fetch_live_24h_trending_news


def ensure_hinglish_filename(text: str, fallback_en: str = "") -> str:
    """Ensures a filename string contains ZERO Devanagari characters and is strictly in Roman/English alphabet (Hinglish)."""
    if not text:
        text = fallback_en or "Daily Trending Story"
    # If contains Devanagari script, convert to Hinglish Roman alphabet
    if re.search(r"[\u0900-\u097F]", text):
        try:
            prompt = (
                f"Convert this Hindi headline into an exciting, natural Hinglish title written strictly in Roman/English alphabet "
                f"(NO Devanagari characters, conversational style like 'Duniya Ka Bada Naya Kadam', max 10-12 words): '{text}'"
            )
            res = llm._generate_response(prompt).strip()
            res = re.sub(r'["\'\*\#\`]', '', res).strip()
            if res and not re.search(r"[\u0900-\u097F]", res) and not res.lower().startswith("error"):
                return gdrive.sanitize_filename(res)
        except Exception as e:
            logger.warning(f"Error converting Hindi to Hinglish filename: {e}")
        # Strip any Devanagari characters as fallback
        cleaned = re.sub(r"[\u0900-\u097F]+", "", text).strip()
        if len(cleaned) > 5:
            return gdrive.sanitize_filename(cleaned)
        fallback = fallback_en if fallback_en else "Trending Story"
        return gdrive.sanitize_filename(f"{fallback} Ka Bada Update")
    return gdrive.sanitize_filename(text)


def get_daily_trending_topics() -> dict:
    """Dynamically fetch the most exciting, viral, and impactful trending story from any category in the past 24 hours."""
    logger.info("Fetching latest 24-hour trending news across all categories...")
    news_items = fetch_live_24h_trending_news()
    past_topics = get_past_topics()

    if news_items:
        news_headlines = "\n".join([f"- {item['title']}" for item in news_items[:15]])
        logger.info(f"Retrieved {len(news_items)} real-time 24h fresh news stories (past topics excluded).")

        past_warning = ""
        if past_topics:
            past_warning = (
                "CRITICAL: Do NOT pick or duplicate any of these previously covered stories:\n"
                + "\n".join([f"- {p}" for p in past_topics[-15:]])
                + "\n\n"
            )

        prompt = (
            "Here are today's top trending news stories and viral events from the past 24 hours across the world:\n"
            f"{news_headlines}\n\n"
            f"{past_warning}"
            "Select the single most fascinating, viral, and engaging story from today's list. "
            "It can be ANY trending topic: world news, viral phenomenon, entertainment, culture, human achievement, mysteries, sports, nature, space, or science. "
            "Create:\n"
            "1. A clean English headline for the English video.\n"
            "2. A compelling, exciting Hindi headline written in Devanagari script for the Hindi video content and narration.\n"
            "3. A catchy Hinglish headline written strictly in Roman/English alphabet (NO Devanagari characters) specifically for the video filename on disk and Google Drive.\n"
            "Requirements:\n"
            "1. Do not use special characters like :, /, \\, *, ?, \", <, > in the titles.\n"
            "2. Keep the titles engaging, catchy, and professional (max 10-14 words).\n"
            "3. 'topic_hi' must be in proper Hindi (Devanagari script).\n"
            "4. 'topic_hi_filename' must be strictly in Roman/English alphabet (Hinglish, zero Devanagari characters) so the video filename is clean and readable.\n"
            "Respond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "topic_en": "Catchy English Headline Here",\n'
            '  "topic_hi": "रोमांचक हिंदी हेडलाइन यहाँ देवनागरी लिपि में",\n'
            '  "topic_hi_filename": "Romanchak Hinglish Headline in Roman Script Here"\n'
            "}"
        )

        try:
            response = llm._generate_response(prompt)
            clean_resp = re.sub(r"```[a-zA-Z]*", "", response).replace("```", "").strip()
            start_idx = clean_resp.find("{")
            end_idx = clean_resp.rfind("}")
            if start_idx != -1 and end_idx != -1:
                data = json.loads(clean_resp[start_idx : end_idx + 1])
                en_title = gdrive.sanitize_filename(data.get("topic_en", ""))
                hi_title = gdrive.sanitize_filename(data.get("topic_hi", ""))
                hi_filename = gdrive.sanitize_filename(data.get("topic_hi_filename", ""))
                if not hi_filename or re.search(r"[\u0900-\u097F]", hi_filename):
                    hi_filename = ensure_hinglish_filename(hi_filename or hi_title, en_title)
                if (
                    en_title
                    and hi_title
                    and not en_title.lower().startswith("error")
                    and not hi_title.lower().startswith("error")
                    and not is_topic_duplicate(en_title, past_topics)
                ):
                    logger.success(f"Dynamic 24h Trending Topic Selected (EN): {en_title}")
                    logger.success(f"Dynamic 24h Trending Topic Selected (HI-Devanagari): {hi_title}")
                    logger.success(f"Dynamic 24h Trending Topic Filename (HI-Hinglish): {hi_filename}")
                    return {"en": en_title, "hi": hi_title, "hi_filename": hi_filename}
        except Exception as e:
            logger.warning(f"Error selecting dynamic trending topic with AI: {e}")

        # Fallback to top unused news headline and translate headline
        for candidate in news_items:
            cand_title = candidate["title"]
            if not is_topic_duplicate(cand_title, past_topics):
                top_headline = gdrive.sanitize_filename(cand_title)
                try:
                    trans_prompt = (
                        f"Translate or adapt this English headline into two formats:\n"
                        f"1. A powerful Hindi headline in Devanagari script.\n"
                        f"2. An exciting Hinglish headline strictly in Roman/English alphabet (NO Devanagari script) for the video filename.\n"
                        f"Headline: '{top_headline}'\n"
                        f"Respond ONLY with valid JSON:\n"
                        f'{{"hi": "देवनागरी हिंदी हेडलाइन", "hi_filename": "Hinglish Headline in Roman Script"}}'
                    )
                    trans_resp = llm._generate_response(trans_prompt).strip()
                    clean_t = re.sub(r"```[a-zA-Z]*", "", trans_resp).replace("```", "").strip()
                    s_idx = clean_t.find("{")
                    e_idx = clean_t.rfind("}")
                    if s_idx != -1 and e_idx != -1:
                        t_data = json.loads(clean_t[s_idx : e_idx + 1])
                        hi_cand = gdrive.sanitize_filename(t_data.get("hi", ""))
                        hi_fn = gdrive.sanitize_filename(t_data.get("hi_filename", ""))
                        if hi_cand and not hi_cand.lower().startswith("error"):
                            hi_fn = ensure_hinglish_filename(hi_fn or hi_cand, top_headline)
                            return {"en": top_headline, "hi": hi_cand, "hi_filename": hi_fn}
                except Exception as te:
                    logger.warning(f"Headline translation fallback: {te}")
                hi_fn = ensure_hinglish_filename(top_headline, top_headline)
                return {
                    "en": top_headline,
                    "hi": f"{top_headline} पर बड़ा अपडेट",
                    "hi_filename": hi_fn,
                }

    # Universal high-variety fallback if completely offline
    import random
    unique_id = random.randint(100, 999)
    return {
        "en": f"Extraordinary Global Discovery and Major Historic Breakthrough {unique_id}",
        "hi": f"दुनिया की सबसे बड़ी खोज और नया ऐतिहासिक मोड़ {unique_id}",
        "hi_filename": f"Duniya Ki Sabse Badi Discovery Aur Naya Mod {unique_id}",
    }


# Backward compatibility alias
get_daily_tech_topics = get_daily_trending_topics


def get_calibrated_fallback_script(topic: str, language: str) -> str:
    """Returns a fast-paced universal script calibrated to ~300-315 words for a rapid-fire 2-minute narration on ANY topic."""
    if language == "hi":
        return (
            f"आज पूरी दुनिया में {topic} को लेकर जबरदस्त चर्चा चल रही है, और यह वायरल खबर सोशल मीडिया से लेकर इंटरनेशनल हेडलाइंस तक सबसे बड़ा ट्रेंडिंग विषय बन चुकी है। "
            "जो घटना शुरुआत में केवल एक सामान्य खबर की तरह दिख रही थी, उसने अब एक बहुत बड़े वैश्विक घटनाक्रम का रूप ले लिया है और इंटरनेट पर आग की तरह फैल चुकी है। "
            "आम लोगों के साथ-साथ दुनिया भर के शीर्ष विश्लेषक, खोजी पत्रकार और रिसर्चर्स भी अब पूरी गंभीरता के साथ इस पूरे मामले पर अपनी नजरें गड़ाए हुए हैं। "
            "इस पूरे घटनाक्रम के पीछे कई ऐसे चौंकाने वाले तथ्य, छिपे हुए पहलू और अप्रत्याशित मोड़ सामने आए हैं, जिन्होंने पुरानी धारणाओं को पूरी तरह बदलकर सभी को नए सिरे से सोचने पर मजबूर कर दिया है। "
            "अंतरराष्ट्रीय रिपोर्ट्स और जमीनी सूत्रों के मुताबिक, इसका सीधा असर न सिर्फ वर्तमान हालात पर पड़ रहा है, बल्कि आने वाले समय में भी इसके बहुत बड़े और दूरगामी परिणाम देखने को मिलेंगे। "
            "हर नया अपडेट यह साफ बता रहा है कि यह सिर्फ एक आम घटना नहीं है, बल्कि एक ऐसा ऐतिहासिक मोड़ है जिसे समझना आज हर किसी के लिए बेहद जरूरी हो गया है। "
            "विशेषज्ञ और वैश्विक पर्यवेक्षक चौबीसों घंटे इस पर बारीक नजर बनाए हुए हैं, क्योंकि हर गुजरते घंटे के साथ नए खुलासे, सनसनीखेज जानकारियां और अनपेक्षित पहलू सामने आ रहे हैं। "
            "लोगों की उत्सुकता इस समय चरम सीमा पर है और हर कोई इसके गहरे प्रभाव को समझने की कोशिश कर रहा है। "
            "यह पूरी कहानी हमें याद दिलाती है कि आज की तेज रफ्तार दुनिया में चीजें कितनी तेजी से बदल सकती हैं और उनका प्रभाव कितना व्यापक हो सकता है। "
            "क्या आप इस बड़े ट्रेंडिंग विषय के सभी पहलुओं से वाकिफ हैं? देश और दुनिया की ऐसी ही सबसे बड़ी वायरल खबरों और गहराई से विश्लेषण के लिए हमारे साथ जुड़े रहिए।"
        )
    else:
        return (
            f"The world is talking about {topic.lower()}, and this explosive story has instantly captured global attention across every major platform and international headline. "
            "What began as a quiet development has rapidly evolved into an overwhelming worldwide phenomenon, sparking relentless discussions and intense fascination among millions of viewers. "
            "At its heart lies a series of stunning revelations that shatter conventional expectations and open up an entirely fresh perspective on what is unfolding in our world right now. "
            "Breaking reports, firsthand investigative accounts, and analytical breakdowns reveal that the real-world implications reach far beyond initial impressions, sending shockwaves across communities and global markets alike. "
            "From unprecedented breakthroughs to dramatic turning points, every single update underscores why this historic development has ignited such extraordinary curiosity and fierce debate across networks. "
            "Leading observers, field researchers, and top commentators are tracking every move around the clock as verified facts and high-stakes developments continue to roll in without pause. "
            "Public interest is surging to all-time highs as audiences worldwide race to understand the broader context and long-term consequences of what has just transpired. "
            "Every newly verified angle confirms that this is not merely a passing headline, but a monumental turning point that demands our immediate attention and deeper scrutiny. "
            "From shocking ground realities to global strategic implications, this developing situation is accelerating faster than anyone anticipated, leaving commentators and researchers searching for answers. "
            "As viral conversations accelerate across every corner of the web, one thing is unmistakable: we are living through a pivotal moment that will shape cultural and historical discussions for years to come. "
            "The lightning speed of this unfolding narrative reminds us how interconnected, dynamic, and unpredictable our modern world truly is today. "
            "Stay tuned for daily high-octane coverage, verified insights, and comprehensive breakdowns of the biggest stories shaping our world."
        )


def enforce_2min_length(script: str, language: str, topic: str) -> str:
    """Strictly bounds word count between 280 and 325 words for fast-paced 1.15x narration to guarantee a ~2 minute (115-125s) video."""
    if not script:
        return get_calibrated_fallback_script(topic, language)

    script = " ".join(script.split())
    words = script.split()

    # If script is too short (< 275 words), it produces < 105s at fast speed
    if len(words) < 275:
        logger.warning(f"Generated script is only {len(words)} words (< 275 words for fast pace). Using calibrated fast 2-minute script.")
        return get_calibrated_fallback_script(topic, language)

    # If script is too long (> 325 words), trim cleanly at sentence boundary to prevent exceeding 2 minutes
    if len(words) > 325:
        logger.warning(f"Generated script is {len(words)} words (> 325 words). Trimming cleanly for fast 2-minute duration.")
        cand = " ".join(words[:325])
        sep = "।" if language == "hi" else "."
        last_punct = max(cand.rfind("."), cand.rfind("?"), cand.rfind("!"), cand.rfind("।"))
        if last_punct != -1 and len(cand[:last_punct + 1].split()) >= 280:
            return cand[:last_punct + 1].strip()
        else:
            return " ".join(words[:305]) + (sep if not cand.endswith(sep) else "")

    return script


FORBIDDEN_META_MARKERS = [
    "we need", "260-280", "260-275", "words in", "single paragraph",
    "content:", "role:", "reasoning", "let's count", "count words",
    "draft:", "here is the script", "here is a script", "sure, here",
    "certainly!", "as requested", "word count",
    "120-second", "narration script", "requirements:", "target words",
    "hook:", "voiceover:", "narrator:", "scene 1", "approximate:",
    "headings", "timestamps", "asterisks", "assistant"
]


def validate_and_sanitize_script(script: str, language: str, topic: str) -> str:
    """
    Strict QA guardrail to verify and sanitize script text before TTS narration.
    Completely eliminates prompt instructions, scratchpad reasoning, JSON dumps, drafts, or language mismatches.
    If the text is in any way compromised, instantly falls back to the clean calibrated story script.
    """
    if not script or len(script.strip()) < 50:
        logger.warning("Script verification FAILED: empty or too short. Using calibrated 2-min narrative.")
        return get_calibrated_fallback_script(topic, language)

    # 1. Clean JSON formatting or role wrappers
    script = script.strip()
    if "{" in script and "}" in script:
        try:
            start_j = script.find("{")
            end_j = script.rfind("}")
            j = json.loads(script[start_j : end_j + 1])
            if isinstance(j, dict):
                if j.get("content"):
                    script = str(j["content"])
                elif j.get("textResponse"):
                    script = str(j["textResponse"])
        except Exception:
            pass

    # 2. Strip conversational introductions
    script = re.sub(
        r"^(?:Here is (?:the|a) (?:2-minute )?script|Sure, here is (?:the|a) script|Script|Narration):\s*",
        "",
        script,
        flags=re.IGNORECASE,
    ).strip()

    s_lower = script.lower()

    # 3. Reject any meta-instruction / reasoning markers
    for marker in FORBIDDEN_META_MARKERS:
        if marker in s_lower:
            logger.warning(f"Script verification FAILED: contains meta marker '{marker}'. Using calibrated 2-min narrative.")
            return get_calibrated_fallback_script(topic, language)

    # 4. Reject raw JSON remnants
    if "{" in script or "}" in script or '":' in script or "tool_calls" in script:
        logger.warning("Script verification FAILED: contains raw JSON syntax. Using calibrated 2-min narrative.")
        return get_calibrated_fallback_script(topic, language)

    # 5. For Hindi ('hi'), verify Devanagari script presence (strictly Hindi Devanagari script)
    if language == "hi":
        if not re.search(r"[\u0900-\u097F]", script):
            logger.warning("Script verification FAILED: missing Devanagari Hindi script. Using calibrated Hindi 2-min narrative.")
            return get_calibrated_fallback_script(topic, language)

    # 6. Bound duration and length cleanly (280 - 325 words for fast-paced 1.15x pace)
    return enforce_2min_length(script, language, topic)


def generate_2min_script(topic: str, language: str) -> tuple[str, list]:
    """
    Generate a fast-paced 2-minute script (~300-315 words, ~120s narration at 1.15x speed) and 16 diverse search terms for ANY trending topic.
    For 'hi', generates authentic Hindi script (Devanagari alphabet) for fast, natural narration.
    """
    try:
        if language == "hi":
            lang_desc = "Hindi (Devanagari script, natural fast-paced Hindi story narration)"
        else:
            lang_desc = "English"

        lang_prompt = (
            f"Write a high-energy, fast-paced, and gripping 2-minute video narration script about the trending topic: '{topic}'.\n"
            f"Requirements:\n"
            f"1) Language: {lang_desc}.\n"
            f"2) Length: Exactly around 300-315 words (calibrated for rapid-fire 120-second narration at high speech rate, do not write less than 285 words and do not write more than 325 words).\n"
            f"3) Format: Single continuous paragraph with natural punctuation (commas, periods, purna viram) for Text-To-Speech. Absolutely no headings, timestamps, asterisks, bullet points, reasoning thoughts, or narrator cues.\n"
            f"4) Content: Open with a razor-sharp hook, jump immediately into the core viral story, cover shocking details and rapid-fire developments, and end with an unforgettable conclusion.\n"
            f"5) Tone: Fast-paced, punchy, energetic viral documentary style with quick transitions and zero slow filler."
        )
        raw_script = llm._generate_response(lang_prompt)
        raw_script = llm._sanitize_llm_output(raw_script)

        # Apply rigorous verification and QA guardrail
        script = validate_and_sanitize_script(raw_script, language, topic)
        logger.info(f"Verified fast-paced 2-min script ({language.upper()}) word count: {len(script.split())} words")

        # Request 16 diverse English visual terms matching the specific topic
        terms = llm.generate_terms(video_subject=topic, video_script=script, amount=16)
        if terms and isinstance(terms, list) and len(terms) >= 6:
            # Dynamic visual terms derived from topic keywords
            topic_words = [w for w in re.findall(r'[a-zA-Z]{4,}', topic) if w.lower() not in ["with", "from", "that", "this", "over", "what", "into"]]
            extra_terms = [
                f"{topic_words[0].lower()} documentary" if topic_words else "breaking news",
                "dramatic cinematic visuals",
                "world news broadcast",
                "stunning nature exploration",
                "people discussing worldwide",
                "historic moment crowd",
                "aerial drone cinematic landscape",
                "global event documentary",
            ]
            for et in extra_terms:
                if len(terms) < 16 and et not in terms:
                    terms.append(et)
            return script, terms
    except Exception as e:
        logger.warning(f"AI script generation fallback triggered: {e}")

    # Fallback to calibrated 2-minute script
    script = get_calibrated_fallback_script(topic, language)
    logger.info(f"Fallback 2-min script ({language.upper()}) word count: {len(script.split())} words")

    # Universal visual terms suitable for general trending events
    terms = [
        "breaking news",
        "cinematic landscape",
        "world event",
        "documentary footage",
        "global city skyline",
        "people celebrating event",
        "scientific discovery",
        "nature exploration",
        "historic moment",
        "aerial drone view",
        "crowd gathering",
        "dramatic visuals",
        "investigative journalism",
        "inspiring story",
        "international summit",
        "modern technology innovation",
    ]
    import random
    random.shuffle(terms)
    return script, terms


def produce_single_video(topic: str, language: str, script: str, terms: list, semantic_script: str = None, filename: str = None) -> str:
    """Generates a 2-minute 16:9 Landscape video using Pexels & Pixabay with 0 duplicate footage clips."""
    task_id = utils.get_uuid()
    logger.info(f"\n==========================================")
    logger.info(f"Generating {language.upper()} Video (2 Minutes, 16:9 Landscape)")
    logger.info(f"Topic: {topic}")
    if filename:
        logger.info(f"Target Filename (Hinglish): {filename}")
    logger.info(f"Task ID: {task_id}")
    logger.info(f"Footage Sources: Pexels + Pixabay Multi-Provider")
    logger.info(f"Visual Terms Count: {len(terms)}")
    logger.info(f"==========================================")

    # Language-specific voice and font
    if language == "hi":
        voice_name = "hi-IN-MadhurNeural-Male"
        font_name = "Nirmala.ttc"
    else:
        voice_name = "chatterbox:default:Default Voice-Neutral"
        font_name = "STHeitiMedium.ttc"

    # Prepare VideoParams for 2-minute 16:9 Landscape video
    params = VideoParams(
        video_subject=topic,
        video_script=script,
        video_terms=terms,
        video_aspect=VideoAspect.landscape.value,  # 16:9 Landscape
        video_concat_mode=VideoConcatMode.semantic.value,  # Semantic text alignment
        video_clip_duration=2,  # Fast-paced dynamic scene transitions every 2 seconds!
        video_count=1,
        video_source="all",  # Use BOTH Pexels and Pixabay!
        voice_name=voice_name,
        voice_volume=1.0,
        voice_rate=1.15,  # 15% faster speech rate for punchy, energetic narration
        bgm_type="random",
        bgm_volume=0.22,  # Dynamic music tempo
        subtitle_enabled=False,
        subtitle_position="bottom",
        font_name=font_name,
        text_fore_color="#FFFF00",  # Yellow text
        font_size=60,
        stroke_color="#000000",
        stroke_width=1.5,
        enable_word_highlighting=False,
        word_highlight_color="#ff0000",  # Red highlight
        max_chars_per_line=50,
        max_lines_per_subtitle=2,
        segmentation_method="sentences",
        min_segment_length=15,  # Snappy phrase segmentation
        similarity_threshold=0.50,
        diversity_threshold=8,
        max_video_reuse=1,  # Strictly NO REPEAT clips across scenes!
        search_pool_size=80,  # Large diverse candidate pool
        semantic_model="all-mpnet-base-v2",
        semantic_script=semantic_script,  # English reference script for Hindi visual alignment
        enable_image_similarity=False,  # Disabled slow CLIP
        image_similarity_threshold=0.7,
        image_similarity_model="clip-vit-base-patch32",
        enable_images=True,  # Enable Pexels & Pixabay stock photos
        image_ratio=0.20,  # Strictly 80% videos : 20% photos proportion
        image_clip_duration=1.3,  # Strictly max 1.3s per photo scene with Ken Burns slow zoom
    )

    result = task.start(task_id, params, stop_at="video")
    task_dir = utils.task_dir(task_id)

    try:
        try:
            from moviepy import AudioFileClip
        except ImportError:
            from moviepy.editor import AudioFileClip
        audio_check = os.path.join(task_dir, "audio.mp3")
        if os.path.exists(audio_check):
            with AudioFileClip(audio_check) as a_clip:
                logger.info(f"Verified Audio Duration ({language.upper()}): {a_clip.duration:.1f}s ({a_clip.duration / 60:.2f} mins)")
    except Exception as ae:
        logger.debug(f"Audio duration check notice: {ae}")

    final_video = os.path.join(task_dir, "final-1.mp4")

    target_video = None
    if os.path.exists(final_video):
        target_video = final_video
    else:
        for f in Path(task_dir).glob("*.mp4"):
            if "combined" not in f.name and "temp" not in f.name:
                target_video = str(f)
                break

    if target_video:
        from app.services import video as video_service
        target_video = video_service.ensure_max_filesize(target_video, max_mb=68.0)
        target_filename = filename if filename else topic
        if language == "hi":
            target_filename = ensure_hinglish_filename(target_filename)
        clean_title = gdrive.sanitize_filename(target_filename)
        topic_named_video = os.path.join(task_dir, f"{clean_title}.mp4")
        try:
            shutil.copy2(target_video, topic_named_video)
            logger.success(f"Video saved as topic title ({language.upper()}): {topic_named_video}")
            return topic_named_video
        except Exception:
            logger.success(f"Video created successfully ({language.upper()}): {target_video}")
            return target_video

    logger.error(f"Video generation failed for {language.upper()}")
    return None


def run_daily_video():
    """Main workflow: Creates BOTH videos first (English & Hindi), then uploads both to their respective Google Drive accounts. Resumes from where it left off if interrupted."""
    logger.info("=== Starting Daily 2-Video Automation Pipeline ===")

    # 1. Wait for internet connection
    if not wait_for_internet():
        logger.error("No internet connection available. Aborting.")
        return

    today_str = datetime.date.today().isoformat()
    state = load_state()

    # If state is from today and already 100% completed, exit
    if state.get("date") == today_str and state.get("completed"):
        logger.info(f"Today's ({today_str}) English and Hindi videos are already generated and uploaded. Exiting.")
        return

    # If state is empty or was completed on an earlier day, initialize fresh state for today
    if not state or state.get("completed"):
        state = {
            "date": today_str,
            "completed": False,
            "topics": {},
            "scripts": {},
            "videos": {},
            "uploads": {},
        }
        save_state(state)

    # ---------------------------------------------------------
    # STEP 1: Fetch Topics (Resume existing if already fetched)
    # ---------------------------------------------------------
    if not state.get("topics", {}).get("en") or not state.get("topics", {}).get("hi"):
        logger.info("Fetching 24h trending topics...")
        topics = get_daily_tech_topics()
        state["topics"] = topics
        save_state(state)
    else:
        topics = state["topics"]
        logger.info(f"Resuming with saved topic: {topics.get('en')}")

    en_topic = topics["en"]
    hi_topic = topics["hi"]
    hi_filename = topics.get("hi_filename") or ensure_hinglish_filename(hi_topic, en_topic)

    # ---------------------------------------------------------
    # STEP 2: Generate English Video First
    # ---------------------------------------------------------
    en_video = state.get("videos", {}).get("en")
    if not en_video or not os.path.exists(en_video):
        logger.info("--- Step 2: Generating English Video ---")
        en_script_data = state.get("scripts", {}).get("en")
        if not en_script_data:
            en_script, en_terms = generate_2min_script(en_topic, language="en")
            state.setdefault("scripts", {})["en"] = {"script": en_script, "terms": en_terms}
            save_state(state)
        else:
            en_script = validate_and_sanitize_script(en_script_data["script"], "en", en_topic)
            en_terms = en_script_data["terms"]
            state["scripts"]["en"]["script"] = en_script
            save_state(state)

        en_video = produce_single_video(en_topic, "en", en_script, en_terms)
        if not en_video or not os.path.exists(en_video):
            logger.error("English video generation failed.")
            return
        state.setdefault("videos", {})["en"] = en_video
        save_state(state)
    else:
        logger.info(f"English video already ready at: {en_video}")

    # ---------------------------------------------------------
    # STEP 3: Generate Hindi Video (BOTH generated before upload!)
    # ---------------------------------------------------------
    hi_video = state.get("videos", {}).get("hi")
    if not hi_video or not os.path.exists(hi_video):
        logger.info("--- Step 3: Generating Hindi Video ---")
        hi_script_data = state.get("scripts", {}).get("hi")
        if not hi_script_data:
            hi_script, hi_terms = generate_2min_script(hi_topic, language="hi")
            state.setdefault("scripts", {})["hi"] = {"script": hi_script, "terms": hi_terms}
            save_state(state)
        else:
            hi_script = validate_and_sanitize_script(hi_script_data["script"], "hi", hi_topic)
            hi_terms = hi_script_data["terms"]
            state["scripts"]["hi"]["script"] = hi_script
            save_state(state)
        en_script_ref = state.get("scripts", {}).get("en", {}).get("script", "")
        hi_video = produce_single_video(hi_topic, "hi", hi_script, hi_terms, semantic_script=en_script_ref, filename=hi_filename)
        if not hi_video or not os.path.exists(hi_video):
            logger.error("Hindi video generation failed.")
            return
        state.setdefault("videos", {})["hi"] = hi_video
        save_state(state)
    else:
        logger.info(f"Hindi video already ready at: {hi_video}")

    logger.success("=== BOTH VIDEOS ARE GENERATED LOCALLY! STARTING UPLOADS ===")

    # ---------------------------------------------------------
    # STEP 4: Upload English Video to English Google Drive
    # ---------------------------------------------------------
    if not state.get("uploads", {}).get("en"):
        logger.info(f"--- Step 4: Uploading English Video to Google Drive ---")
        for attempt in range(1, 6):
            try:
                en_res = gdrive.upload_video(en_video, account_name="english", file_title=en_topic)
                if en_res:
                    state.setdefault("uploads", {})["en"] = en_res
                    save_state(state)
                    break
            except Exception as e:
                logger.error(f"English Drive upload attempt {attempt}/5 error: {e}")
                if attempt < 5:
                    time.sleep(10)
    else:
        logger.info("English video already uploaded to Google Drive.")

    # ---------------------------------------------------------
    # STEP 5: Upload Hindi Video to Hindi Google Drive
    # ---------------------------------------------------------
    if not state.get("uploads", {}).get("hi"):
        logger.info(f"--- Step 5: Uploading Hindi Video to Google Drive ---")
        hi_file_title = topics.get("hi_filename") or ensure_hinglish_filename(hi_topic, en_topic)
        for attempt in range(1, 6):
            try:
                hi_res = gdrive.upload_video(hi_video, account_name="hindi", file_title=hi_file_title)
                if hi_res:
                    state.setdefault("uploads", {})["hi"] = hi_res
                    save_state(state)
                    break
            except Exception as e:
                logger.error(f"Hindi Drive upload attempt {attempt}/5 error: {e}")
                if attempt < 5:
                    time.sleep(10)
    else:
        logger.info("Hindi video already uploaded to Google Drive.")

    # Mark entire daily pipeline completed only if both uploads succeeded
    if state.get("uploads", {}).get("en") and state.get("uploads", {}).get("hi"):
        state["completed"] = True
        save_state(state)
        record_run_result(status="success", results=[
            {"language": "english", "topic": en_topic, "status": "success", "local_path": en_video, "gdrive": state["uploads"].get("en")},
            {"language": "hindi", "topic": hi_topic, "filename": hi_filename, "status": "success", "local_path": hi_video, "gdrive": state["uploads"].get("hi")},
        ])
        logger.success("=== Daily 2-Video Pipeline Completed & Both Videos Uploaded Successfully! ===")
    else:
        state["completed"] = False
        save_state(state)
        logger.warning("Uploads incomplete due to network issue. Will retry uploading on next run.")


if __name__ == "__main__":
    run_daily_video()
