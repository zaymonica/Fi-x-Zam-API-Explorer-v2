"""
routes/downloader.py — Unified Downloader API
Handles proxying / downloading of .mp4 and converting .m3u8 on the fly to .mp4
using FFmpeg with per-domain User-Agent headers.
"""
import subprocess
import logging
from urllib.parse import urlparse
from flask import Blueprint, request, redirect, Response
from utils import json_response

downloader_bp = Blueprint('downloader', __name__)
log = logging.getLogger(__name__)

# ── Domain → User-Agent mapping ──────────────────────────────────────
# Some CDNs reject requests from FFmpeg's default User-Agent (Lavf/...).
# This mapping mirrors the User-Agent each provider route uses when
# talking to its upstream, so FFmpeg can fetch segments without 403s.
DOMAIN_UA_MAP = {
    # FlickReels (farsunpteltd)
    "farsunpteltd.com": "MyUserAgent",
    # GoodShort
    "goodshort": "okhttp/4.10.0",
    # FreeReels / DramaWave (mydramawave)
    "mydramawave.com": "okhttp/4.12.0",
    # ShortMax (shorttv.live / akamai)
    "shorttv.live": "okhttp/4.12.0",
    # Melolo / MeloShort (melolostatic / byteintlapi)
    "melolostatic.com": "okhttp/4.12.0",
    "byteintlapi.com": "okhttp/4.12.0",
    # DramaBox (supabase edge → usually its own CDN)
    "supabase.co": "SonzaiX-API/1.0",
    # NetShort / DramaKuy
    "dramakuy.com": "Mozilla/5.0 (Linux; Android 12; SM-A156E Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/110.0.5481.154 Mobile Safari/537.36",
    # PineDrama (tiktokcdn)
    "tiktokcdn.com": "okhttp/4.12.0",
    # ReelShort
    "reelshort.com": "okhttp/4.12.0",
    # DramaNova
    "dramanova": "okhttp/4.12.0",
}

# Fallback user-agent when no domain matches
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"


def _get_user_agent(url: str) -> str:
    """Pick the best User-Agent for the given video URL based on its domain."""
    hostname = urlparse(url).hostname or ""
    for domain_key, ua in DOMAIN_UA_MAP.items():
        if domain_key in hostname:
            return ua
    return DEFAULT_UA


@downloader_bp.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    filename = request.args.get('filename', 'episode.mp4')
    subtitle_url = request.args.get('subtitle')  # Optional external .srt/.vtt URL

    if not url:
        return json_response({"error": "Provide ?url= parameter"}, 400)

    # Ensure filename has .mp4 extension for output
    if not filename.endswith('.mp4'):
        filename += '.mp4'

    # If it's already an mp4 (not m3u8) and no subtitle to merge, just redirect.
    if '.m3u8' not in url.lower() and url.lower().endswith('.mp4') and not subtitle_url:
        return redirect(url)

    # Determine the right User-Agent for this CDN
    user_agent = _get_user_agent(url)

    # Build FFmpeg command
    # -user_agent: pass the correct UA so CDNs don't return 403
    # -map 0:v:0 / 0:a:0: pick only the BEST (first) video and audio from HLS adaptive
    # frag_keyframe+empty_moov: allows MP4 streaming over HTTP (fragmented mp4)
    cmd = [
        'ffmpeg',
        '-user_agent', user_agent,
        '-i', url,
    ]

    if subtitle_url:
        # ── Subtitle mode: download .srt, burn into video ────────────────
        # We must re-encode video to burn subtitles into the frames.
        # This is slower but guarantees subtitle visibility on ALL players.
        import tempfile, os, requests as http_req

        # Download .srt/.vtt to a temp file (ffmpeg subtitles filter needs a local file)
        try:
            r = http_req.get(subtitle_url, timeout=15)
            r.raise_for_status()
            sub_ext = '.vtt' if '.vtt' in subtitle_url.lower() else '.srt'
            tmp_sub = tempfile.NamedTemporaryFile(delete=False, suffix=sub_ext, dir='/tmp')
            tmp_sub.write(r.content)
            tmp_sub.close()
        except Exception as e:
            return json_response({"error": "Failed to download subtitle", "detail": str(e)}, 502)

        # Map only best video + audio
        cmd.extend(['-map', '0:v:0', '-map', '0:a:0'])

        # Burn subtitle into video using the subtitles filter
        # Escape special chars in path for ffmpeg filter
        safe_path = tmp_sub.name.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
        cmd.extend([
            '-vf', f"subtitles='{safe_path}':force_style='FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2'",
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov',
            'pipe:1'
        ])

        # Store temp path so we can clean up later
        _subtitle_tmp = tmp_sub.name
    else:
        # ── No subtitle: fast copy mode ──────────────────────────────────
        cmd.extend(['-map', '0:v:0', '-map', '0:a:0', '-map', '0:s?'])
        cmd.extend([
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-c:s', 'mov_text',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov',
            'pipe:1'
        ])
        _subtitle_tmp = None

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except Exception as e:
        return json_response({"error": "Failed to start ffmpeg process", "detail": str(e)}, 500)

    def generate():
        try:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            process.stdout.close()
            process.wait()
            stderr_output = process.stderr.read().decode('utf-8', errors='replace')
            process.stderr.close()
            if process.returncode != 0 and stderr_output:
                log.warning("ffmpeg failed (rc=%d) for url=%s: %s",
                            process.returncode, url, stderr_output[-500:])
            # Cleanup temp subtitle file
            if _subtitle_tmp and os.path.exists(_subtitle_tmp):
                try:
                    os.remove(_subtitle_tmp)
                except:
                    pass

    # Check if ffmpeg started successfully by reading a small initial chunk
    initial_chunk = process.stdout.read(65536)
    if not initial_chunk:
        process.stdout.close()
        process.wait()
        stderr_output = process.stderr.read().decode('utf-8', errors='replace')
        process.stderr.close()
        if _subtitle_tmp and os.path.exists(_subtitle_tmp):
            try:
                os.remove(_subtitle_tmp)
            except:
                pass
        log.error("ffmpeg failed immediately for url=%s: %s", url, stderr_output[-500:])
        return json_response({
            "error": "FFmpeg failed to process the video URL",
            "detail": stderr_output[-300:] if stderr_output else "No output from ffmpeg"
        }, 502)

    def generate_with_initial():
        yield initial_chunk
        try:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            process.stdout.close()
            process.wait()
            stderr_output = process.stderr.read().decode('utf-8', errors='replace')
            process.stderr.close()
            if process.returncode != 0 and stderr_output:
                log.warning("ffmpeg failed (rc=%d) for url=%s: %s",
                            process.returncode, url, stderr_output[-500:])
            # Cleanup temp subtitle file
            if _subtitle_tmp and os.path.exists(_subtitle_tmp):
                try:
                    os.remove(_subtitle_tmp)
                except:
                    pass

    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Type': 'video/mp4'
    }

    return Response(generate_with_initial(), headers=headers)
