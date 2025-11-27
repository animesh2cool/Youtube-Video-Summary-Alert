import os
import time
import json
import glob
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Libraries
import yt_dlp
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Parse multiple channels from comma-separated string
CHANNEL_URLS_RAW = os.getenv("CHANNEL_URLS")
# Create a list of URLs, removing whitespace
CHANNEL_URLS = [url.strip() for url in CHANNEL_URLS_RAW.split(",")] if CHANNEL_URLS_RAW else []

CHECK_INTERVAL = 3000
MODEL_NAME = "gemini-2.5-pro"

# Email Configuration
OUTLOOK_EMAIL = os.getenv("OUTLOOK_EMAIL")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_CC = os.getenv("EMAIL_CC")

# Initialize Gemini Client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# State File for Multiple Channels
STATE_FILE = "channel_state.json"

def get_latest_video_from_channel(channel_url):
    """
    Uses yt-dlp to scrape the latest video from a channel.
    """
    # Force the /videos tab
    if not channel_url.endswith('/videos'):
        target_url = f"{channel_url.rstrip('/')}/videos"
    else:
        target_url = channel_url

    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'playlistend': 5,
        'ignoreerrors': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            
            if 'entries' in info:
                for entry in info['entries']:
                    if not entry: continue
                    video_id = entry.get('id')
                    title = entry.get('title')

                    # Ignore Channel IDs
                    if video_id and video_id.startswith('UC'):
                        continue
                    
                    return video_id, title
            
            return None, None
    except Exception as e:
        print(f"Error fetching channel info for {channel_url}: {e}")
        return None, None

def get_video_transcript_ytdlp(video_id):
    """
    Uses yt-dlp to download auto-generated subtitles (VTT), 
    parses them into text, and cleans up the file.
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = f"transcript_{video_id}"
    
    ydl_opts = {
        'skip_download': True,
        'writeautomaticsub': True,
        'writesub': True,
        'sublangs': ['en.*', 'en'],
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        vtt_files = glob.glob(f"{output_template}*.vtt")
        
        if not vtt_files:
            print("No subtitle file downloaded.")
            return None

        vtt_file_path = vtt_files[0]
        full_text = []

        with open(vtt_file_path, 'r', encoding='utf-8') as f:
            seen_lines = set()
            for line in f:
                line = line.strip()
                if (not line or 
                    "-->" in line or 
                    line.startswith("WEBVTT") or 
                    line.startswith("Kind:") or 
                    line.startswith("Language:") or
                    line.startswith("NOTE")):
                    continue
                
                if line not in seen_lines:
                    full_text.append(line)
                    seen_lines.add(line)
                    if len(seen_lines) > 5: 
                        seen_lines.pop()

        os.remove(vtt_file_path)
        return " ".join(full_text)

    except Exception as e:
        print(f"Error extracting transcript: {e}")
        for f in glob.glob(f"{output_template}*.vtt"):
            try: os.remove(f)
            except: pass
        return None

def generate_insights(video_title, transcript_text):
    """Sends transcript to Gemini for analysis."""
    print(" Analyzing with Gemini...")
    
    prompt = f"""
    You are an AI assistant specialized in summarizing YouTube videos.
    
    Video Title: One engaging headline that captures {video_title} topic.
    
    Transcript:
    {transcript_text[:30000]}
    
 
    Your task is to generate a concise, professional summary suitable for automated delivery. 
    exactly:

    Summary Length: 5-10 sentences.

    Structure:

    Summary: Core insights, key points, and actionable takeaways.

    Key Insights or Takeaways (bullet points).

    Optional Notes: Any relevant context or caveats.

    Tone & Style: Professional, clear, neutral, and easy to read.

    Content Accuracy: Summarize faithfully without adding personal opinions.

    Formatting: Use plain text or simple markdown for clarity.

    """

    try:
        response = gemini_client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3
            )
        )
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return None

def save_insights_to_file(video_title, insights_text):
    """Saves the generated insights to a Markdown file."""
    safe_title = "".join([c for c in video_title if c.isalnum() or c in (' ', '-', '_')]).strip()
    safe_title = safe_title.replace(" ", "_")
    filename = f"insight_{safe_title}.md"
    
    os.makedirs("insights", exist_ok=True)
    filepath = os.path.join("insights", filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Insights: {video_title}\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(insights_text)
    
    print(f"Saved insights to: {filepath}")

def send_outlook_email(subject, body_content, video_id):
    """Sends a beautifully formatted HTML email using Outlook SMTP."""
    if not OUTLOOK_EMAIL or not OUTLOOK_PASSWORD:
        return

    try:
        # Convert markdown-style content to HTML
        import re
        
        # Extract sections from the body_content
        lines = body_content.split('\n')
        summary = ""
        key_insights = []
        optional_notes = ""
        
        current_section = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if 'summary:' in line.lower():
                current_section = 'summary'
                continue
            elif 'key insights' in line.lower() or 'takeaways' in line.lower():
                current_section = 'insights'
                continue
            elif 'optional notes' in line.lower() or 'notes:' in line.lower():
                current_section = 'notes'
                continue
            
            # Process content based on section
            if current_section == 'summary':
                # Remove ** markers
                cleaned = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', line)
                summary += cleaned + " "
            elif current_section == 'insights':
                if line.startswith('*') or line.startswith('-') or line.startswith('•'):
                    cleaned = line.lstrip('*-• ').strip()
                    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', cleaned)
                    key_insights.append(cleaned)
            elif current_section == 'notes':
                cleaned = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', line)
                optional_notes += cleaned + " "
        
        # Build HTML email
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
        }}
        .email-container {{
            max-width: 650px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 700;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        .header .icon {{
            font-size: 48px;
            margin-bottom: 10px;
        }}
        .video-thumbnail {{
            width: 100%;
            height: 300px;
            object-fit: cover;
            display: block;
        }}
        .content {{
            padding: 40px 35px;
        }}
        .video-title {{
            font-size: 24px;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 20px;
            line-height: 1.4;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 700;
            color: #667eea;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
        }}
        .section-title::before {{
            content: '';
            width: 4px;
            height: 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin-right: 10px;
            border-radius: 2px;
        }}
        .summary-text {{
            font-size: 16px;
            line-height: 1.8;
            color: #4a5568;
            background: #f7fafc;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .insights-list {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .insights-list li {{
            font-size: 15px;
            line-height: 1.7;
            color: #4a5568;
            padding: 15px 20px;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #f7fafc 0%, #edf2f7 100%);
            border-radius: 8px;
            border-left: 4px solid #48bb78;
            position: relative;
            padding-left: 50px;
        }}
        .insights-list li::before {{
            content: '✓';
            position: absolute;
            left: 20px;
            top: 50%;
            transform: translateY(-50%);
            background: #48bb78;
            color: white;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 14px;
        }}
        .notes {{
            background: #fff5f5;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #fc8181;
            font-size: 15px;
            line-height: 1.7;
            color: #4a5568;
        }}
        .cta-button {{
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 16px 40px;
            text-decoration: none;
            border-radius: 50px;
            font-weight: 700;
            font-size: 16px;
            margin-top: 30px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
            transition: transform 0.2s;
        }}
        .cta-button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
        }}
        .footer {{
            background: #2d3748;
            color: #a0aec0;
            padding: 25px;
            text-align: center;
            font-size: 13px;
        }}
        .footer a {{
            color: #667eea;
            text-decoration: none;
        }}
        .divider {{
            height: 2px;
            background: linear-gradient(90deg, transparent, #e2e8f0, transparent);
            margin: 30px 0;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="icon">📺</div>
            <h1>YouTube Insights Report</h1>
        </div>
        
        <a href="{video_url}" target="_blank">
            <img src="{video_thumbnail}" alt="Video Thumbnail" class="video-thumbnail" />
        </a>
        
        <div class="content">
            <h2 class="video-title">{subject}</h2>
            
            {f'''
            <div class="section">
                <h3 class="section-title">📋 Summary</h3>
                <div class="summary-text">
                    {summary}
                </div>
            </div>
            ''' if summary else ''}
            
            {f'''
            <div class="divider"></div>
            
            <div class="section">
                <h3 class="section-title">💡 Key Insights & Takeaways</h3>
                <ul class="insights-list">
                    {"".join([f"<li>{insight}</li>" for insight in key_insights])}
                </ul>
            </div>
            ''' if key_insights else ''}
            
            {f'''
            <div class="divider"></div>
            
            <div class="section">
                <h3 class="section-title">📌 Additional Notes</h3>
                <div class="notes">
                    {optional_notes}
                </div>
            </div>
            ''' if optional_notes else ''}
            
            <div style="text-align: center;">
                <a href="{video_url}" class="cta-button" target="_blank">
                    ▶ Watch Full Video
                </a>
            </div>
        </div>
        
        <div class="footer">
            <p>Generated by YouTube Monitor • {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
            <p>This is an automated summary. <a href="{video_url}">Watch the full video</a> for complete details.</p>
        </div>
    </div>
</body>
</html>
"""

        msg = MIMEMultipart('alternative')
        msg['From'] = OUTLOOK_EMAIL
        msg['To'] = EMAIL_TO
        msg['Cc'] = EMAIL_CC
        msg['Subject'] = f"📺 YouTube Insight: {subject}"

        recipients = []
        if EMAIL_TO: recipients.append(EMAIL_TO)
        if EMAIL_CC: recipients.append(EMAIL_CC)
        
        if not recipients:
            return

        # Attach plain text version as fallback
        plain_text = f"""
YouTube Insights Report
======================

Video: {subject}
Watch: {video_url}

{body_content}

---
Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
"""
        
        msg.attach(MIMEText(plain_text, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP('smtp.office365.com', 587)
        server.starttls()
        server.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        
        server.sendmail(OUTLOOK_EMAIL, recipients, msg.as_string())
        server.quit()
        
        print(f"✅ Beautiful HTML email sent successfully to {recipients}")

    except Exception as e:
        print(f"❌ Failed to send email: {e}")

# --- New State Management for Multiple Channels ---
def load_state():
    """Loads the JSON state file tracking last video per channel."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    """Saves the JSON state file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def main():
    print(f"--- YouTube Monitor Started for {len(CHANNEL_URLS)} channels ---")
    
    if not CHANNEL_URLS:
        print("Error: CHANNEL_URLS is missing from .env file.")
        print("Please add: CHANNEL_URLS=url1,url2,url3")
        return

    while True:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"[{current_time}] Starting check cycle...")
        
        # Load current state (dictionary of channel_url -> video_id)
        state = load_state()
        
        for channel_url in CHANNEL_URLS:
            print(f"Checking: {channel_url}")
            
            latest_id, latest_title = get_latest_video_from_channel(channel_url)
            
            # Get the last processed ID for *this specific channel*
            last_processed_id = state.get(channel_url)

            if latest_id:
                # Check for new video (Length check > 5 helps avoid garbage IDs)
                if len(latest_id) > 5 and latest_id != last_processed_id:
                    print(f"New Video Detected: {latest_title} (ID: {latest_id})")
                    
                    transcript = get_video_transcript_ytdlp(latest_id)
                    
                    if transcript:
                        insights = generate_insights(latest_title, transcript)
                        
                        if insights:
                            print("\n" + "="*50)
                            print(f" INSIGHTS FOR: {latest_title}")
                            print("="*50)
                            print(insights)
                            print("="*50 + "\n")
                            
                            save_insights_to_file(latest_title, insights)
                            
                            print("Sending email...")
                            send_outlook_email(latest_title, insights, latest_id)
                            
                            # Update state ONLY for this channel and save immediately
                            state[channel_url] = latest_id
                            save_state(state)
                        else:
                            print("Failed to generate insights.")
                    else:
                        print("Skipping analysis (No transcript available).")
                elif latest_id == last_processed_id:
                    print("No new videos (ID match).")
            else:
                print("Could not retrieve video list.")
            
            # Polite delay between channel checks
            time.sleep(2)

        print(f"Cycle complete. Waiting {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()