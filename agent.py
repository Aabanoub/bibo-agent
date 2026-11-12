import os
import asyncio
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import icalendar
import recurring_ical_events
import edge_tts
from google import genai

# 1. Load Secrets Safely
ICAL_URL = os.environ.get("ICAL_URL", "").strip()
TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

CAIRO_TZ = ZoneInfo("Africa/Cairo")
TODAY = datetime.now(CAIRO_TZ).date()
HEADERS = {"User-Agent": "bibo-agent/1.0 (https://github.com/Aabanoub/bibo-agent)"}

# 2. Fetch Cairo Weather (Fast & Free: met.no primary, wttr.in backup)
def get_weather():
    # Attempt 1: Norwegian Meteorological Institute (Fast on GitHub Actions, no API key)
    try:
        url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=30.0444&lon=31.2357"
        res = requests.get(url, headers=HEADERS, timeout=8).json()
        timeseries = res["properties"]["timeseries"]
        curr = timeseries[0]["data"]["instant"]["details"]["air_temperature"]
        next_temps = [t["data"]["instant"]["details"]["air_temperature"] for t in timeseries[:8]]
        return f"Current: {curr}°C (High: {max(next_temps)}°C, Low: {min(next_temps)}°C)"
    except Exception as e:
        print(f"Primary weather skipped ({e}), trying backup...")

    # Attempt 2: wttr.in Backup
    try:
        res = requests.get("https://wttr.in/Cairo?format=j1", headers=HEADERS, timeout=8).json()
        curr = res["current_condition"][0]["temp_C"]
        high = res["weather"][0]["maxtempC"]
        low = res["weather"][0]["mintempC"]
        return f"Current: {curr}°C (High: {high}°C, Low: {low}°C)"
    except Exception as e:
        print(f"Backup weather skipped ({e})")
        return "Weather forecast unavailable today."

# 3. Fetch Today's Google Calendar Events
def get_calendar_events():
    if not ICAL_URL.startswith("http"):
        return "No Google Calendar connected."
    try:
        res = requests.get(ICAL_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        cal = icalendar.Calendar.from_ical(res.text)
        events = recurring_ical_events.of(cal).at(TODAY)
        event_list = []
        for event in events:
            summary = str(event.get("SUMMARY", "Busy"))
            start = event.get("DTSTART").dt
            start_local = start.astimezone(CAIRO_TZ).strftime("%I:%M %p") if isinstance(start, datetime) else "All Day"
            event_list.append(f"- {start_local}: {summary}")
        return "\n".join(event_list) if event_list else "No calendar events scheduled for today."
    except Exception as e:
        print(f"Calendar warning: {e}")
        return "Could not load calendar events today."

# 4. Fetch Today's Todoist Tasks
def get_todoist_tasks():
    if not TODOIST_TOKEN:
        return "No Todoist tasks connected."
    try:
        headers = {"Authorization": f"Bearer {TODOIST_TOKEN}"}
        res = requests.get(
            "https://api.todoist.com/rest/v2/tasks",
            params={"filter": "today | overdue"},
            headers=headers,
            timeout=10
        )
        if res.status_code != 200:
            return "No tasks loaded."
        tasks = res.json()
        return "\n".join([f"- {t['content']}" for t in tasks]) if tasks else "No pending tasks for today."
    except Exception as e:
        print(f"Todoist warning: {e}")
        return "Could not load tasks today."

# 5. Summarize with Gemini
def generate_voice_script(weather, events, tasks):
    if not GEMINI_API_KEY:
        raise ValueError("Missing GEMINI_API_KEY in GitHub Secrets!")
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    You are a friendly, energetic personal assistant for Bibo. Write a 45-second spoken morning briefing 
    for today ({TODAY.strftime('%A, %B %d, %Y')}).
    Write strictly for spoken audio (Text-to-Speech). Do NOT use markdown, asterisks (*), or bullet points.

    Weather in Cairo: {weather}
    Calendar Schedule: {events}
    Tasks Due Today: {tasks}
    """
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
    )
    return response.text

# 6. Convert Text to Telegram Voice Note (.ogg Opus)
async def text_to_ogg(script_text):
    voice = "en-US-AndrewNeural"
    communicate = edge_tts.Communicate(script_text, voice)
    await communicate.save("briefing.mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", "briefing.mp3",
        "-c:a", "libopus", "-b:a", "32k", "-vbr", "on",
        "briefing.ogg"
    ], check=True)

# 7. Send Voice Note to Telegram
def send_telegram_voice():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in GitHub Secrets!")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVoice"
    with open("briefing.ogg", "rb") as voice_file:
        res = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"voice": voice_file},
            timeout=30
        )
        print("Telegram API response:", res.text)
        res.raise_for_status()

async def main():
    print("1/5 Fetching weather...")
    weather = get_weather()
    print("2/5 Fetching calendar...")
    events = get_calendar_events()
    print("3/5 Fetching tasks...")
    tasks = get_todoist_tasks()
    print("4/5 Generating Gemini script...")
    script = generate_voice_script(weather, events, tasks)
    print("5/5 Generating audio & sending to Telegram...")
    await text_to_ogg(script)
    send_telegram_voice()
    print("SUCCESS: Voice note sent to Telegram!")

if __name__ == "__main__":
    asyncio.run(main())
