# Music Content Automation Pipeline

Automated pipeline that generates music concepts, creates tracks, thumbnails, videos, and uploads to YouTube and TikTok.

## Pipeline Steps

1. **Concept Generation** -- GPT-4o-mini generates track name, genre, mood, lyrics, thumbnail prompt, and platform metadata
2. **Music Generation** -- Playwright automates [aimusicfactory.ai](https://aimusicfactory.ai/) to create and download an MP3
3. **Thumbnail Generation** -- DALL-E 3 generates album cover art (1792x1024)
4. **Video Creation** -- MoviePy composites thumbnail + audio into YouTube (16:9) and TikTok (9:16) videos with Ken Burns zoom effect
5. **YouTube Upload** -- Playwright automates YouTube Studio upload flow
6. **TikTok Upload** -- Playwright automates TikTok Creator Center upload flow

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your OpenAI API key:

```
OPENAI_API_KEY=sk-your-actual-key-here
```

### 3. Export browser cookies for YouTube and TikTok

The pipeline uses browser cookies to authenticate with YouTube Studio and TikTok. You need to export cookies from a logged-in browser session.

#### Option A: Using a browser extension (recommended)

1. Install a cookie export extension like [EditThisCookie](https://chromewebstore.google.com/detail/editthiscookie/) or [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/)
2. Log in to YouTube Studio (https://studio.youtube.com) in your browser
3. Click the extension icon and export cookies as JSON
4. Save to `cookies/youtube_cookies.json`
5. Repeat for TikTok (https://www.tiktok.com) and save to `cookies/tiktok_cookies.json`

#### Option B: Using browser DevTools

1. Open YouTube Studio in Chrome, press F12 to open DevTools
2. Go to **Application** tab > **Cookies** on the left sidebar
3. Right-click > copy all cookies, then format as JSON array:

```json
[
  {
    "name": "cookie_name",
    "value": "cookie_value",
    "domain": ".youtube.com",
    "path": "/",
    "secure": true,
    "httpOnly": true
  }
]
```

4. Save to `cookies/youtube_cookies.json`
5. Repeat for TikTok and save to `cookies/tiktok_cookies.json`

#### Cookie JSON format

Each file should be a JSON array of cookie objects. The required fields per cookie are:

| Field | Description |
|-------|-------------|
| `name` | Cookie name |
| `value` | Cookie value |
| `domain` | Domain (e.g., `.youtube.com`) |
| `path` | Path (usually `/`) |

Optional fields: `secure`, `httpOnly`, `sameSite`, `expires`.

### 4. Create cookies directory

```bash
mkdir -p cookies
```

## Usage

### Run the pipeline once

```bash
python main.py run
```

This executes all 6 steps sequentially:
- Generates a random music concept using OpenAI
- Creates the music track on aimusicfactory.ai via browser automation
- Generates a thumbnail with DALL-E 3
- Creates YouTube (landscape) and TikTok (portrait) videos with MoviePy
- Uploads to YouTube Studio with title, description, tags, and custom thumbnail
- Uploads to TikTok with caption and hashtags

Output files are saved to the `output/` directory.

### Run on a schedule

```bash
# Default: daily at 10:00 AM (configured in .env)
python main.py schedule

# Custom cron expression
python main.py schedule --cron "0 9 * * 1-5"
```

Press `Ctrl+C` to stop the scheduler.

### Run with visible browser (for debugging)

Set `HEADLESS=false` in `.env` to see the browser automation in real time. Useful for:
- First-time setup to verify cookie authentication works
- Debugging when selectors break due to site DOM changes
- Monitoring the upload flow

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | OpenAI API key for GPT-4o-mini and DALL-E 3 |
| `MUSIC_GENRE_POOL` | `pop,lofi,jazz,...` | Comma-separated genres to randomly pick from |
| `SCHEDULE_CRON` | `0 10 * * *` | Cron expression for scheduled runs |
| `YOUTUBE_COOKIE_FILE` | `cookies/youtube_cookies.json` | Path to YouTube cookies |
| `TIKTOK_COOKIE_FILE` | `cookies/tiktok_cookies.json` | Path to TikTok cookies |
| `OUTPUT_DIR` | `output` | Directory for generated files |
| `HEADLESS` | `true` | Run browsers in headless mode |

## Project Structure

```
music/
  main.py                   # CLI entry point (run / schedule)
  pipeline.py               # Pipeline orchestrator (6 steps)
  config.py                 # Environment variable loader
  requirements.txt          # Python dependencies
  .env.example              # Template for .env
  modules/
    concept_generator.py    # Step 1: OpenAI concept generation
    music_generator.py      # Step 2: aimusicfactory.ai automation
    thumbnail_generator.py  # Step 3: DALL-E 3 image generation
    video_creator.py        # Step 4: MoviePy video assembly
    youtube_uploader.py     # Step 5: YouTube Studio upload
    tiktok_uploader.py      # Step 6: TikTok upload
  utils/
    browser.py              # Shared Playwright browser context + cookie management
    logger.py               # Centralized logging
  cookies/                  # Browser cookies (gitignored)
  output/                   # Generated files (gitignored)
```

## Troubleshooting

**"Not logged in" errors**: Your cookies have expired. Re-export fresh cookies from your browser.

**Selector errors on aimusicfactory.ai**: The site's DOM may have changed. Run with `HEADLESS=false`, inspect the page, and update the selectors in `modules/music_generator.py`.

**YouTube upload fails at "Next" step**: YouTube Studio's DOM changes frequently. Check `output/debug_youtube_error.png` for a screenshot and update selectors in `modules/youtube_uploader.py`.

**MoviePy/FFmpeg errors**: Ensure FFmpeg is installed: `sudo apt install ffmpeg` (Linux) or `brew install ffmpeg` (macOS).
