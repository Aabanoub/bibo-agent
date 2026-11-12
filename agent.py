import os
import asyncio
import subprocess
from datetime import datetime, date
from zoneinfo import ZoneInfo
import requests
import icalendar
import recurring_ical_events
import edge_tts
from google import genai

# 1. Load Secrets from Environment Variables
ICAL_URL = os.environ["ICAL_URL"]
TODOIST_TOKEN = os.environ["TODOIST_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

CAIRO_TZ = ZoneInfo("Africa/Cairo")
TODAY = datetime.now(CAIRO_TZ).date()

# 2. Fetch Cairo Weather (100% Free, No API Key via Open-Meteo)
def get_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=30.0444&longitude=31.2357"
        "&current=temperature_2m,apparent_temperature"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&timezone=Africa%2FCairo&forecast_days=1"
    )
    res = requests.get(url, timeout=10).json()
    curr = res["current"]["temperature_2m"]
    high = res["daily"]["temperature_2m_max"][0]
    low = res["daily"]["temperature_2m_min"][0]
    return f"Current: {curr}°C (High: {high}°C, Low: {low}°C)"

# 3. Fetch Today's Google Calendar Events (via Free Secret .ics URL)
def get_calendar_events():
    res = requests.get(ICAL_URL, timeout=15)
    cal = icalendar.Calendar.from_ical(res.text)
    events = recurring_ical_events.of(cal).at(TODAY)
    
    event_list = []
    for event in events:
        summary = str(event.get("SUMMARY", "Busy"))
        start = event.get("DTSTART").dt
        if isinstance(start, datetime):
            start_local = start.astimezone(CAIRO_TZ).strftime("%I:%M %p")
        else:
            start_local = "All Day"
        event_list.append(f"- {start_local}: {summary}")
    
    return "\n".join(event_list) if event_list else "No calendar events scheduled for today."

# 4. Fetch Today's Todoist Tasks
def get_todoist_tasks():
    headers = {"Authorization": f"Bearer {TODOIST_TOKEN}"}
    res = requests.get(
        "https://api.todoist.com/rest/v2/tasks",
        params={"filter": "today | overdue"},
        headers=headers,
        timeout=10
    )
    if res.status_code != 200:
        return "Could not fetch tasks."
    tasks = res.json()
    if not tasks:
        return "No pending tasks for today."
    return "\n".join([f"- {t['content']} (Priority {t['priority']})" for t in tasks])

# 5. Summarize with Gemini (Free Tier)
def generate_voice_script(weather, events, tasks):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    You are a friendly, energetic personal assistant. Write a 45-to-60-second spoken morning briefing 
    for today ({TODAY.strftime('%A, %B %d, %Y')}).
    
    Rules:
    - Write strictly for spoken audio (Text-to-Speech).
    - Do NOT use markdown, asterisks (*), bullet points, or emojis.
    - Keep it natural, motivating, and concise.

    Data for today:
    Weather in Cairo: {weather}
    Calendar Schedule:
    {events}
    Tasks Due Today:
    {tasks}
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

# 6. Convert Text to Telegram Voice Note (.ogg Opus) using Free Edge-TTS
async def text_to_ogg(script_text):
    # Popular free neural voices:
    # English: "en-US-AndrewNeural" or "en-US-AriaNeural"
    # Egyptian Arabic: "ar-EG-SalmaNeural" or "ar-EG-ShakirNeural"
    voice = "en-US-AndrewNeural"
    communicate = edge_tts.Communicate(script_text, voice)
    await communicate.save("briefing.mp3")
    
    # Convert MP3 to OGG Opus so Telegram displays it as a playable voice waveform
    subprocess.run([
        "ffmpeg", "-y", "-i", "briefing.mp3",
        "-c:a", "libopus", "-b:a", "32k", "-vbr", "on",
        "briefing.ogg"
    ], check=True)

# 7. Send Voice Note to Telegram
def send_telegram_voice():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVoice"
    with open("briefing.ogg", "rb") as voice_file:
        requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"voice": voice_file},
            timeout=30
        )

async def main():
    weather = get_weather()
    events = get_calendar_events()
    tasks = get_todoist_tasks()
    script = generate_voice_script(weather, events, tasks)
    await text_to_ogg(script)
    send_telegram_voice()

if __name__ == "__main__":
    asyncio.run(main())
