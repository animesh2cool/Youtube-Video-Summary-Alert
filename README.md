# Youtube-Video-Summary-Alert
This is a robust, automated surveillance tool designed to monitor multiple YouTube channels for new content. By leveraging yt-dlp for data extraction and Google's Gemini 2.5 Pro for cognitive analysis, it provides instant summaries and insights without requiring a YouTube Data API quota.

When a new video is detected on any target channel, the system automatically fetches the transcript, generates an executive summary, archives the report locally, and dispatches an email notification.

Key Features :

  Multi-Channel Support: Monitor 5, 10, or more channels simultaneously via a simple configuration list.

  Zero-Quota Extraction: Uses yt-dlp to scrape video metadata and auto-generated captions, removing the need for a YouTube Data API key.

  AI-Driven Insights: distinct analysis including a 3-4 sentence summary, bulleted key takeaways, and sentiment tone analysis using the Gemini 2.5 Pro model.

  Instant Email Alerts: Sends real-time email notifications (via Outlook/SMTP) for every new upload detected.

  Local Archiving: Automatically saves all generated insights as Markdown files (.md) in a local insights/ directory.

  Smart State Management: Tracks the last processed video for each channel individually using a JSON state file, ensuring no duplicate alerts.
