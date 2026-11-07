import asyncio
import logging
import os
import random
import time
from pathlib import Path
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen, Request
import json
import re
from difflib import SequenceMatcher

import yt_dlp
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.types import BotCommand
import pyrogram.errors as pe

pe.GroupcallForbidden = pe.BadRequest
pe.GroupcallInvalid = pe.BadRequest

from pytgcalls import PyTgCalls, filters as call_filters
from pytgcalls.types import StreamEnded
from ntgcalls import MediaSource
from pytgcalls.types.raw import Stream, AudioStream, AudioParameters, VideoStream, VideoParameters

logging.basicConfig(level=logging.WARNING)
load_dotenv(Path(__file__).with_name(".env"))

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not API_ID or not API_HASH or not BOT_TOKEN:
    raise SystemExit("Check API_ID, API_HASH and BOT_TOKEN in .env")

BASE = Path(__file__).resolve().parent
CACHE = BASE / "music" / "youtube_cache"
CACHE.mkdir(parents=True, exist_ok=True)

bot = Client("abhi_music_bot", api_id=API_ID, api_hash=API_HASH,
             bot_token=BOT_TOKEN, workers=1)
user = Client("abhi_music_user", api_id=API_ID, api_hash=API_HASH,
             session_string=os.getenv("STRING_SESSION") or None, workers=1)
calls = None
queues, current, autoplay, locks, suppress_end = {}, {}, {}, {}, {}
nexting = set()
next_pending = set()

def get_lock(cid):
    if cid not in locks:
        locks[cid] = asyncio.Lock()
    return locks[cid]

def keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ⅱ ᴘᴀᴜsᴇ", callback_data="pause"),
            InlineKeyboardButton("▶ ʀᴇsᴜᴍᴇ", callback_data="resume"),
            InlineKeyboardButton("ɴᴇxᴛ ⟫", callback_data="skip")
        ],
        [
            InlineKeyboardButton("♧ ǫᴜᴇᴜᴇ", callback_data="queue"),
            InlineKeyboardButton("■ sᴛᴏᴘ", callback_data="stop")
        ]
    ])

def is_youtube_url(text):
    try:
        u = urlparse(text.strip())
        return u.scheme in ("http", "https") and (
            u.hostname == "youtu.be" or
            (u.hostname or "").endswith("youtube.com"))
    except Exception:
        return False

def is_spotify_url(text):
    try:
        u = urlparse(text.strip())
        return u.hostname in ("open.spotify.com", "www.spotify.com") and (
            u.path.startswith("/track/"))
    except Exception:
        return False


def spotify_track_query(url):
    endpoint = "https://open.spotify.com/oembed?" + urlencode({"url": url})
    with urlopen(endpoint, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    title = (data.get("title") or "").strip()
    artist = (data.get("author_name") or "").strip()
    if not title:
        raise RuntimeError("Spotify link se track details nahi mil sake")
    return f"{title} {artist}".strip()


def search_match_score(query, title):
    """Score how closely a search result title matches the requested track."""
    stop = {
        "new", "song", "songs", "latest", "official", "audio", "video",
        "lyrics", "lyric", "full", "hd", "4k", "music", "status",
        " slowed", "reverb"
    }
    q_words = re.findall(r"[a-z0-9]+", (query or "").lower())
    q_words = [w for w in q_words if w not in stop and len(w) > 1]
    t_words = re.findall(r"[a-z0-9]+", (title or "").lower())
    if not q_words or not t_words:
        return 0.0
    # Also compare joined neighboring words (e.g. "chal re" vs "chalre").
    title_words = set(t_words)
    title_words.update(t_words[i] + t_words[i + 1] for i in range(len(t_words) - 1))
    unique_query = list(dict.fromkeys(q_words))
    matched = 0
    for word in unique_query:
        best = max((SequenceMatcher(None, word, candidate).ratio()
                    for candidate in title_words), default=0.0)
        if best >= 0.70:
            matched += 1
    token_score = matched / len(unique_query)
    phrase_score = SequenceMatcher(
        None, " ".join(unique_query), " ".join(t_words)
    ).ratio()
    return max(token_score, phrase_score * 0.85)



def download_track_invidious(query, random_mode=False):
    """YouTube-only audio fallback through public Invidious frontends."""
    instances = [
        "https://inv.nadeko.net",
        "https://invidious.nerdvpn.de",
        "https://invidious.privacyredirect.com",
        "https://iv.datura.network",
    ]
    search_query = (
        "latest popular Hindi Indian Bollywood songs official audio"
        if random_mode else
        (spotify_track_query(query) if is_spotify_url(query) else query)
    )
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ABHIMusicRoyal/1.0)"}
    last_error = None

    for base in instances:
        try:
            search_url = base + "/api/v1/search?" + urlencode({
                "q": search_query, "type": "video"
            })
            req = Request(search_url, headers=headers)
            with urlopen(req, timeout=12) as response:
                results = json.loads(response.read().decode("utf-8"))
            videos = [
                item for item in results
                if item.get("type") == "video" and item.get("videoId")
            ]
            if random_mode:
                random.shuffle(videos)
            else:
                videos.sort(
                    key=lambda item: search_match_score(
                        search_query, item.get("title") or ""
                    ),
                    reverse=True,
                )
                matched_videos = [
                    item for item in videos
                    if search_match_score(
                        search_query, item.get("title") or ""
                    ) >= 0.45
                ]
                # Devanagari Hindi titles may not score with the Latin-token matcher.
                # In that case, trust Invidious' own relevance order.
                videos = matched_videos if matched_videos else videos

            for item in videos[:5]:
                video_id = item["videoId"]
                details_url = base + "/api/v1/videos/" + video_id
                req = Request(details_url, headers=headers)
                with urlopen(req, timeout=15) as response:
                    details = json.loads(response.read().decode("utf-8"))
                streams = [
                    stream for stream in (details.get("adaptiveFormats") or [])
                    if (stream.get("type") or "").startswith("audio/")
                    and stream.get("url")
                ]
                if not streams:
                    continue
                streams.sort(
                    key=lambda stream: int(stream.get("bitrate") or 0),
                    reverse=True,
                )
                audio_url = streams[0]["url"]
                target = CACHE / (video_id + "_invidious_audio")
                req = Request(audio_url, headers=headers)
                with urlopen(req, timeout=30) as response, target.open("wb") as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                if target.is_file() and target.stat().st_size > 0:
                    return (
                        str(target),
                        details.get("title") or item.get("title") or "YouTube track",
                        int(details.get("lengthSeconds") or item.get("lengthSeconds") or 0),
                    )
        except Exception as exc:
            last_error = exc
            logging.warning("Invidious fallback %s failed: %s", base, exc)

    raise RuntimeError(
        "YouTube yt-dlp aur Invidious fallback dono se audio nahi mila. "
        "Public Invidious instances kabhi-kabhi unavailable ho sakte hain. "
        f"Last fallback error: {last_error}"
    )

def download_track(query, random_mode=False):
    """Search and play Indian music from YouTube only; never substitute another service."""
    opts = {
        "format": "bestaudio[acodec!=none]/bestaudio/best",
        "outtmpl": str(CACHE / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }

    search_query = spotify_track_query(query) if is_spotify_url(query) else query
    if random_mode:
        search_query = "latest popular Hindi Indian Bollywood songs official audio"

    if is_youtube_url(query):
        candidates = [query]
    else:
        # Bias text searches toward Indian/Hindi music while preserving the
        # requested title for strict relevance scoring.
        yt_query = search_query
        if not random_mode and not re.search(r"\\b(hindi|bollywood|indian)\\b", search_query, re.I):
            yt_query += " Hindi Indian song"
        target = "ytsearch10:" + yt_query
        try:
            search_opts = dict(opts)
            search_opts["extract_flat"] = "in_playlist"
            with yt_dlp.YoutubeDL(search_opts) as search_ydl:
                search_info = search_ydl.extract_info(target, download=False)
            entries = [
                item for item in ((search_info or {}).get("entries") or [])
                if item and item.get("id")
            ]
        except Exception as exc:
            logging.warning("YouTube search failed; trying Invidious: %s", exc)
            return download_track_invidious(query, random_mode)

        if random_mode:
            random.shuffle(entries)
        else:
            ranked = sorted(
                entries,
                key=lambda item: search_match_score(
                    search_query, item.get("title") or ""
                ),
                reverse=True,
            )
            entries = [
                item for item in ranked
                if search_match_score(search_query, item.get("title") or "") >= 0.55
            ]
            if not entries:
                return download_track_invidious(query, random_mode)
        candidates = [
            item.get("webpage_url") or item.get("url") or
            ("https://www.youtube.com/watch?v=" + item["id"])
            for item in entries
        ]

    last_error = None
    with yt_dlp.YoutubeDL(opts) as ydl:
        for candidate in candidates:
            try:
                info = ydl.extract_info(candidate, download=True)
                if info and info.get("entries"):
                    info = next((item for item in info["entries"] if item), None)
                if not info:
                    continue
                path = None
                for item in info.get("requested_downloads") or []:
                    candidate_path = item.get("filepath")
                    if candidate_path and Path(candidate_path).is_file():
                        path = candidate_path
                        break
                if not path:
                    prepared = ydl.prepare_filename(info)
                    if Path(prepared).is_file():
                        path = prepared
                if not path:
                    matches = list(CACHE.glob(f"{info.get('id', '')}.*"))
                    if matches:
                        path = str(matches[0])
                if path:
                    return (
                        str(path),
                        info.get("title", "Music track"),
                        int(info.get("duration") or 0),
                    )
            except Exception as exc:
                last_error = exc
                logging.warning("Skipping YouTube result %s: %s", candidate, exc)

    logging.warning("yt-dlp could not download a result; trying Invidious: %s", last_error)
    return download_track_invidious(query, random_mode)


def download_video_track(query):
    """Find the requested song's YouTube video only."""
    opts = {
        "format": "best[height<=360][ext=mp4]/best[height<=360]/best",
        "outtmpl": str(CACHE / "video_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }

    if is_youtube_url(query):
        candidates = [query]
    elif urlparse(query).scheme in ("http", "https"):
        raise RuntimeError("Video ke liye YouTube URL ya song ka naam do.")
    else:
        yt_query = query
        if not re.search(r"\\b(hindi|bollywood|indian)\\b", query, re.I):
            yt_query += " Hindi Indian song official video"
        try:
            search_opts = dict(opts)
            search_opts["extract_flat"] = "in_playlist"
            with yt_dlp.YoutubeDL(search_opts) as search_ydl:
                search_info = search_ydl.extract_info(
                    "ytsearch10:" + yt_query, download=False
                )
            entries = [
                item for item in ((search_info or {}).get("entries") or [])
                if item and item.get("id")
            ]
        except Exception as exc:
            raise RuntimeError(
                "YouTube video search block/fail ho gaya. GitHub runner par "
                "YouTube cookies/session ki zarurat ho sakti hai. "
                f"Details: {exc}"
            ) from exc

        entries = sorted(
            entries,
            key=lambda item: search_match_score(query, item.get("title") or ""),
            reverse=True,
        )
        entries = [
            item for item in entries
            if search_match_score(query, item.get("title") or "") >= 0.55
        ]
        if not entries:
            raise RuntimeError(
                "YouTube par is song ka matching video nahi mila; random video nahi chalaya."
            )
        candidates = [
            item.get("webpage_url") or item.get("url") or
            ("https://www.youtube.com/watch?v=" + item["id"])
            for item in entries
        ]

    last_error = None
    with yt_dlp.YoutubeDL(opts) as ydl:
        for candidate in candidates:
            try:
                info = ydl.extract_info(candidate, download=True)
                if info and info.get("entries"):
                    info = next((item for item in info["entries"] if item), None)
                if not info:
                    continue
                path = None
                for item in info.get("requested_downloads") or []:
                    file_path = item.get("filepath")
                    if file_path and Path(file_path).is_file():
                        path = file_path
                        break
                if not path:
                    prepared = ydl.prepare_filename(info)
                    if Path(prepared).is_file():
                        path = prepared
                if not path:
                    matches = list(CACHE.glob(f"video_{info.get('id', '')}.*"))
                    if matches:
                        path = str(matches[0])
                if path:
                    return str(path), info.get("title", "Video"), int(info.get("duration") or 0)
            except Exception as exc:
                last_error = exc
                logging.warning("Skipping YouTube video %s: %s", candidate, exc)

    raise RuntimeError(
        "YouTube se matching video download nahi hua. Bot-check aane par "
        "cookies/session authentication ki zarurat hogi. "
        f"Last error: {last_error}"
    )


async def play_video_track(cid, query):
    async with get_lock(cid):
        preparing = await bot.send_message(
            cid, "🎬 Finding a video source and preparing the stream…"
        )
        source, title, duration = await asyncio.to_thread(
            download_video_track, query
        )
        pcm = await make_pcm(source, title)
        audio = AudioStream(
            MediaSource.FILE, str(pcm), AudioParameters(48000, 1)
        )
        video = VideoStream(
            MediaSource.FILE, str(source), VideoParameters(640, 360, 20)
        )
        await calls.play(
            cid, Stream(microphone=audio, camera=video)
        )

        stop_timeline(current.get(cid))
        current[cid] = {
            "title": title,
            "query": query,
            "source": source,
            "duration": duration,
            "started_at": time.monotonic(),
            "paused_at": None,
            "paused_total": 0,
            "message_id": None,
            "is_video": True,
        }
        track = current[cid]
        caption = (
            "<b>ꫝʙ፝֟ʜɪㅤᴹᵘᶳᶤᶜ 🎬</b>\\n"
            "<i>ɴᴏᴡ ᴘʟᴀʏɪɴɢ — ᴠɪᴅᴇᴏ</i>\\n\\n"
            f"🎥 <b>{title}</b>{timeline_text(track)}\\n\\n"
            "━━━━━━━━━━━━━━━━━━━━\\n"
            "<i>ʙʏ :- Aʙнɪ ϻᴇᴇɴᴀ ᥫ᭡</i>\\n"
            "➤ @Abhiiiii009"
        )
        sent = await bot.send_photo(
            cid,
            photo=str(Path(__file__).parent / "abhi_royal_theme.png"),
            caption=caption,
            reply_markup=keyboard(),
            parse_mode=ParseMode.HTML,
        )
        try:
            await preparing.delete()
        except Exception:
            pass
        if current.get(cid) is track:
            track["message_id"] = sent.id
            track["timeline_task"] = asyncio.create_task(
                update_timeline(cid, track, sent)
            )

async def make_pcm(source, title):
    pcm = CACHE / (Path(source).stem + "_playback.pcm")
    if pcm.is_file():
        size = pcm.stat().st_size
        if size > 0 and size % 9600 == 0:
            return pcm
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", source, "-vn", "-f", "s16le", "-ac", "1", "-ar", "48000",
        str(pcm), stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode or not pcm.exists() or pcm.stat().st_size == 0:
        raise RuntimeError("FFmpeg conversion failed: " +
                           err.decode(errors="replace")[-250:])
    size = pcm.stat().st_size
    padding = (-size) % 9600
    if padding:
        with pcm.open("ab") as f:
            f.write(b"\x00" * padding)
    return pcm

async def play_track(cid, query, random_mode=False):
    async with get_lock(cid):
        preparing = await bot.send_message(cid, "🎧 Preparing your song…")
        source, title, duration = await asyncio.to_thread(
            download_track, query, random_mode)
        pcm = await make_pcm(source, title)
        audio = AudioStream(
            MediaSource.FILE, str(pcm), AudioParameters(48000, 1))
        await calls.play(cid, Stream(microphone=audio))
        stop_timeline(current.get(cid))
        current[cid] = {
            "title": title,
            "query": query,
            "source": source,
            "duration": duration,
            "started_at": time.monotonic(),
            "paused_at": None,
            "paused_total": 0,
            "message_id": None,
        }
        track = current[cid]
        caption = (
            "<b>ꫝʙ፝֟ʜɪㅤᴹᵘᶳᶤᶜ 🎶</b>\\n"
            "<i>ɴᴏᴡ ᴘʟᴀʏɪɴɢ 🎶</i>\\n\\n"
            f"🎧 <b>{title}</b>{timeline_text(track)}\\n\\n"
            "━━━━━━━━━━━━━━━━━━━━\\n"
            "<i>ʙʏ :- Aʙнɪ ϻᴇᴇɴᴀ ᥫ᭡</i>\\n"
            "➤ @Abhiiiii009"
        )
        sent = await bot.send_photo(
            cid,
            photo=str(Path(__file__).parent / "abhi_royal_theme.png"),
            caption=caption,
            reply_markup=keyboard(),
            parse_mode=ParseMode.HTML
        )
        try:
            await preparing.delete()
        except Exception:
            pass
        if current.get(cid) is track:
            track["message_id"] = sent.id
            track["timeline_task"] = asyncio.create_task(
                update_timeline(cid, track, sent)
            )

def format_time(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def timeline_text(track):
    duration = int(track.get("duration") or 0)
    now = time.monotonic()
    paused_at = track.get("paused_at")
    end_time = paused_at if paused_at is not None else now
    elapsed = int(end_time - track.get("started_at", now) - track.get("paused_total", 0))
    elapsed = min(max(0, elapsed), duration) if duration else max(0, elapsed)

    if duration > 0:
        filled = min(12, int(12 * elapsed / duration))
        bar = "━" * filled + "●" + "━" * (12 - filled)
        return f"\n\n{format_time(elapsed)} {bar} {format_time(duration)}"
    return "\n\n" + format_time(elapsed) + " elapsed"


def stop_timeline(track):
    if not track:
        return
    task = track.get("timeline_task")
    if task and not task.done():
        task.cancel()


def set_timer_paused(cid, paused):
    track = current.get(cid)
    if not track:
        return
    now = time.monotonic()
    paused_at = track.get("paused_at")
    if paused and paused_at is None:
        track["paused_at"] = now
    elif not paused and paused_at is not None:
        track["paused_total"] = track.get("paused_total", 0) + now - paused_at
        track["paused_at"] = None


async def update_timeline(cid, track, message):
    while current.get(cid) is track:
        await asyncio.sleep(5)
        if current.get(cid) is not track:
            break
        if track.get("paused_at"):
            continue
        duration = int(track.get("duration") or 0)
        if duration and time.monotonic() - track["started_at"] - track.get("paused_total", 0) >= duration:
            break
        try:
            caption = (
                "<b>ꫝʙ፝֟ʜɪㅤᴹᵘᶳᶤᶜ 🎶</b>\n"
                "<i>ɴᴏᴡ ᴘʟᴀʏɪɴɢ 🎶</i>\n\n"
                f"🎧 <b>{track['title']}</b>"
                f"{timeline_text(track)}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<i>ʙʏ :- Aʙнɪ ϻᴇᴇɴᴀ ᥫ᭡</i>\n"
                "➤ @Abhiiiii009"
            )
            await bot.edit_message_caption(
                cid, message.id, caption=caption,
                reply_markup=keyboard(), parse_mode=ParseMode.HTML
            )
        except Exception:
            logging.exception("Timeline update failed for chat %s", cid)
            break


async def next_track(cid, manual=False):
    if cid in nexting:
        if manual:
            next_pending.add(cid)
            logging.info("Queued pending manual NEXT for chat %s", cid)
        else:
            logging.warning(
                "Ignoring duplicate stream-end request for chat %s", cid
            )
        return

    nexting.add(cid)
    try:
        while True:
            q = queues.setdefault(cid, [])
            if q:
                query = q.pop(0)
                random_mode = False
            elif autoplay.get(cid, True):
                query = ""
                random_mode = True
            else:
                stop_timeline(current.get(cid))
                current.pop(cid, None)
                return

            try:
                await play_track(cid, query, random_mode)
            except Exception as exc:
                logging.exception("Next-track playback failed")
                await bot.send_message(
                    cid,
                    f"❌ Next track failed: {type(exc).__name__}: {exc}"
                )

            if cid not in next_pending:
                break

            next_pending.discard(cid)
            logging.info("Processing pending NEXT for chat %s", cid)
    finally:
        nexting.discard(cid)
        next_pending.discard(cid)


async def on_stream_end(client, update):
    if not isinstance(update, StreamEnded):
        return
    cid = update.chat_id
    if time.monotonic() < suppress_end.get(cid, 0):
        return
    await next_track(cid)

async def is_admin(message):
    if not message.from_user:
        return False
    if str(message.chat.type).lower().endswith("private"):
        return True
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return str(member.status).lower() in ("administrator", "owner")
    except Exception:
        return False

async def control_allowed(message):
    if await is_admin(message):
        return True
    await message.reply_text("🔒 Group playback controls are admin-only.")
    return False

@bot.on_message(filters.command(["start", "help"]))
async def start(_, message):
    await message.reply_text(
        "♛ <b>━━━━━━━━━━━━━━━━━━</b> ♛\n"
        "<b>      ABHI MUSIC</b>\n"
        "<b>      ROYAL EDITION</b>\n"
        "♛ <b>━━━━━━━━━━━━━━━━━━</b> ♛\n\n"
        "🎵 <b>MUSIC COMMANDS</b>\n"
        "› <code>/play song name</code> — Play music\n"
        "› <code>/search song name</code> — Search & play\n"
        "› <code>/random</code> — Random music\n"
        "› <code>/queue song name</code> — Add to queue\n"
        "› <code>/queue</code> — View queue\n\n"
        "🎛 <b>PLAYER CONTROLS</b>\n"
        "› <code>/pause</code>  •  <code>/resume</code>\n"
        "› <code>/skip</code>  •  <code>/stop</code>\n"
        "› <code>/autoplay on|off</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 <i>Group controls: admins only</i>\n"
        "♬ <b>Enjoy the Royal Sound ♬</b>",
        parse_mode=ParseMode.HTML
    )

@bot.on_message(filters.command("play"))
async def play_cmd(_, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Use: /play song name, YouTube link, or Spotify track link")
    try:
        await message.reply_text(
            "━━━━━━━━━━━━━━━━━━━━\\n"
            "♛ <b>𝐀𝐁𝐇𝐈 𝐌𝐔𝐒𝐈𝐂</b> ♛\\n"
            "◈ <b>𝐏𝐑𝐄𝐏𝐀𝐑𝐈𝐍𝐆 𝐘𝐎𝐔𝐑 𝐓𝐑𝐀𝐂𝐊</b> ◈\\n"
            "♫ <i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ᴡʜɪʟᴇ ᴛʜᴇ ᴍᴜsɪᴄ ɢᴇᴛs ʀᴇᴀᴅʏ…</i>\\n"
            "━━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.HTML
        )
        await play_track(message.chat.id, parts[1])
    except Exception as exc:
        logging.exception("Playback failed")
        await message.reply_text(
            "❌ Music Couldn’t Be Played!\n\n"
            "🎧 To play a song, please add the assistant account @Abhiiiii009 "
            "to the group and grant it permission to play music in the voice chat.\n\n"
            "✅ Once added, please try /play again."
        )


@bot.on_message(filters.command("vplay"))
async def vplay_cmd(_, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text(
            "Use: /vplay video name or a supported video URL"
        )
    try:
        await play_video_track(message.chat.id, parts[1])
    except Exception as exc:
        logging.exception("Video playback failed")
        await message.reply_text(
            f"❌ Video playback failed: {type(exc).__name__}: {exc}"
        )

@bot.on_message(filters.command("search"))
async def search_cmd(_, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Use: /search song name")
    try:
        await message.reply_text("🔎 Searching Indian/Hindi songs on YouTube…")
        await play_track(message.chat.id, parts[1])
    except Exception as exc:
        await message.reply_text(f"❌ Search failed: {type(exc).__name__}: {exc}")

@bot.on_message(filters.command("random"))
async def random_cmd(_, message):
    try:
        await message.reply_text("🎲 Finding a random song…")
        await play_track(message.chat.id, "", True)
    except Exception as exc:
        await message.reply_text(f"❌ Random play failed: {type(exc).__name__}: {exc}")

@bot.on_message(filters.command("queue"))
async def queue_cmd(_, message):
    cid = message.chat.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        queues.setdefault(cid, []).append(parts[1])
        return await message.reply_text("♛ Added to queue: " + parts[1])
    q = queues.setdefault(cid, [])
    playing = current.get(cid)
    lines = [f"🎵 Playing: {playing['title']}"] if playing else ["🎵 Nothing playing"]
    lines += [f"{i}. {item}" for i, item in enumerate(q, 1)]
    await message.reply_text("♛ <b>ROYAL QUEUE</b> ♛\n\n" + "\n".join(lines),
                             parse_mode=ParseMode.HTML)

@bot.on_message(filters.command("autoplay"))
async def autoplay_cmd(_, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        return await message.reply_text("Use: /autoplay on or /autoplay off")
    autoplay[message.chat.id] = parts[1].lower() == "on"
    await message.reply_text("♛ Autoplay " + parts[1].upper())

@bot.on_message(filters.command("pause"))
async def pause_cmd(_, message):
    if not await control_allowed(message):
        return
    try:
        await calls.pause(message.chat.id)
        set_timer_paused(message.chat.id, True)
        await message.reply_text("⏸ Paused")
    except Exception as exc:
        await message.reply_text(f"Pause failed: {exc}")

@bot.on_message(filters.command("resume"))
async def resume_cmd(_, message):
    if not await control_allowed(message):
        return
    try:
        await calls.resume(message.chat.id)
        set_timer_paused(message.chat.id, False)
        await message.reply_text("▶ Resumed")
    except Exception as exc:
        await message.reply_text(f"Resume failed: {exc}")

@bot.on_message(filters.command("skip"))
async def skip_cmd(_, message):
    cid = message.chat.id
    try:
        suppress_end[cid] = time.monotonic() + 3
        await calls.leave_call(cid)
        stop_timeline(current.get(cid))
        current.pop(cid, None)
        await asyncio.sleep(0.4)
        await next_track(cid, manual=True)
    except Exception as exc:
        await message.reply_text(f"Skip failed: {exc}")

@bot.on_message(filters.command("stop"))
async def stop_cmd(_, message):
    cid = message.chat.id
    try:
        suppress_end[cid] = time.monotonic() + 3
        queues[cid] = []
        stop_timeline(current.get(cid))
        current.pop(cid, None)
        await calls.leave_call(cid)
        await message.reply_text("⏹ Stopped; queue cleared")
    except Exception as exc:
        await message.reply_text(f"Stop failed: {exc}")

@bot.on_message(filters.command("status"))
async def status_cmd(_, message):
    await message.reply_text(
        "♛ Royal bot is running." +
        (f"\n🎵 {current[message.chat.id]['title']}"
         if message.chat.id in current else "\nNo tracked song playing."))

async def callback_is_admin(query):
    if query.message.chat.type == "private":
        return True
    try:
        member = await bot.get_chat_member(
            query.message.chat.id, query.from_user.id
        )
        return str(member.status).lower() in ("administrator", "owner")
    except Exception:
        return False

@bot.on_callback_query()
async def buttons(_, query):
    # Acknowledge quickly so Telegram's callback query does not expire.
    try:
        await query.answer()
    except Exception:
        return

    action = query.data
    if not query.message:
        return

    cid = query.message.chat.id

    if action == "queue":
        q = queues.setdefault(cid, [])
        try:
            await query.message.reply_text(
                "\\n".join(q) if q else "♛ Queue is empty"
            )
        except Exception:
            pass
        return

    try:
        if action == "pause":
            await calls.pause(cid)
            set_timer_paused(cid, True)
        elif action == "resume":
            await calls.resume(cid)
            set_timer_paused(cid, False)
        elif action == "skip":
            suppress_end[cid] = time.monotonic() + 3
            await calls.leave_call(cid)
            stop_timeline(current.get(cid))
            current.pop(cid, None)
            await asyncio.sleep(0.4)
            await next_track(cid, manual=True)
        elif action == "stop":
            suppress_end[cid] = time.monotonic() + 3
            queues[cid] = []
            stop_timeline(current.get(cid))
            current.pop(cid, None)
            await calls.leave_call(cid)
        else:
            return

        try:
            await query.message.reply_text("♛ " + action.capitalize())
        except Exception:
            pass
    except Exception as exc:
        logging.exception("Player button failed: %s", action)
        try:
            await query.message.reply_text(
                f"❌ {action.capitalize()} failed: {type(exc).__name__}"
            )
        except Exception:
            pass

async def main():
    global calls
    calls = PyTgCalls(user)
    calls.add_handler(on_stream_end, call_filters.stream_end())
    await user.start()
    await calls.start()
    await bot.start()
    await bot.set_bot_commands([
        BotCommand("play", "Play music"),
        BotCommand("vplay", "Start video streaming"),
        BotCommand("playrtmps", "Play Live Video"),
        BotCommand("playforce", "Force play audio"),
        BotCommand("vplayforce", "Force play video"),
        BotCommand("pause", "Pause the stream"),
        BotCommand("resume", "Resume the stream"),
        BotCommand("skip", "Skip the current track"),
    ])
    print("ABHI MUSIC ROYAL EDITION started")
    try:
        await asyncio.Event().wait()
    finally:
        try:
            await calls.stop()
        except Exception:
            pass
        try:
            await bot.stop()
        except Exception:
            pass
        try:
            await user.stop()
        except Exception:
            pass

if __name__ == "__main__":
    bot.run(main())
