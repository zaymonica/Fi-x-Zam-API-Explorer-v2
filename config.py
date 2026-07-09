"""
config.py — Central configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Server ──────────────────────────────────────────────────────────
PORT  = int(os.getenv('PORT', 5000))
HOST  = os.getenv('HOST', '0.0.0.0')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# ── CORS ────────────────────────────────────────────────────────────
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, age-range',
}

# ── API Branding ────────────────────────────────────────────────────
API_AUTHOR  = os.getenv('API_AUTHOR', 'Sonzai X シ')
API_CONTACT = os.getenv('API_CONTACT', 'https://t.me/November2k')
ADMIN_PASSWORD_HASH = "5c6058f3aa0a004c491c3aa890eafcb5"  # md5("admeme404")

# ── Worker Proxy ────────────────────────────────────────────────────
WORKER_PROXY = "https://proxy.sonzaixlab.workers.dev"

# ── Cookies (Social Media Downloader) ───────────────────────────────
IG_COOKIE = os.getenv('IG_COOKIE', "ig_did=1CE8B205-24AA-491A-9A66-042601D27B30; csrftoken=hIdJUCeyizQwpPfuroip_5; datr=PNF6aSzhX2jWIVO8C2YBnz32; wd=1280x881; mid=aXrRPAALAAG2fayiMjkqm_kSJvSJ; ds_user_id=7182507078; sessionid=7182507078%3AJbaY3ndx7sk4AG%3A4%3AAYjfywjnGlSP_bruaENTCeRo9YlgIQmBKeo0J6vERQ; rur=\"CCO\\0547182507078\\0541801193599:01fed4fedf6bf98d5a6e95e8ce6e989669726a747b4d5eb83fb4e31c08c81e9e4759ec42\"")
FB_COOKIE  = os.getenv('FB_COOKIE', "datr=6-N6aQ_-Rj3emU25IlfTBfr9; fr=15JD0LRluAyiThi8j.AWdWQcv9G73L5q5YA8871LTnOLB9i0nB1NHYw8vSswTrsKAntMM.BpeuV_..AAA.0.0.BpeuV_.AWf7K7lMs7sQgmUsYN7zvrf78qc; sb=6-N6aQVfnnX177VCCju36Iv6; wd=1280x881; locale=id_ID; c_user=100024092658097; xs=27%3AhEAhHRJF43fZew%3A2%3A1769661821%3A-1%3A-1%3A%3AAcz2NZaZRf1FfdkU5BECv1LE4neb0zDGv9YQmMKspw; presence=C%7B%22t3%22%3A%5B%5D%2C%22utc3%22%3A1769661831375%2C%22v%22%3A1%7D")

# ── Shinigami ───────────────────────────────────────────────────────
SHINIGAMI_API_URL    = 'https://api.shngm.io'
SHINIGAMI_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'
SHINIGAMI_PROXY_BASE = os.getenv('SHINIGAMI_PROXY_BASE', 'https://corsproxy.io/')
SHINIGAMI_PROXY_KEYS = [
    key.strip()
    for key in os.getenv('SHINIGAMI_PROXY_KEYS', 'ad24c5b8,f0ce13dc,d1e79e35').split(',')
    if key.strip()
]


# ── Drama (Drakor) ──────────────────────────────────────────────────
DRAMA_API_BASE = "https://api.drakor.la/v2"
DRAMA_COOKIE = os.getenv('DRAKOR_COOKIE', '')
DRAMA_HEADERS  = {
    'User-Agent': 'Dart/3.9 (dart:io)',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip',
    'content-type': 'application/json',
    'x-app-package': 'net.drakorid.app',
    'x-app-version': '7.2',
    'platform': 'Mobile',
    'authorization': 'QJxcWdaEayEePQyIk51TnoTBBqB-I3MFfDry-81U_3SOwvHzFzhVHv_PhE4hpGK4_p3hJ32r-Lj1DPaeB7ZOslz_2AeyG1BjsziQH0kSrZJ6S3adzJCwoWf6qvROrXreBk5qs39dzlrHnDJe2KwEVS7j7Ml7qFf_fbJpw_-MRD7ilFkK_v0Ql5sI3OQb3pG3AwFZ6eR64RbB4tMEq9TYscXrFpHChx3qvyS5RYx3pS9EB02x9xXGeAoUIhiJzhuggXRZDpVXGSAdNbmwXr8It3Od1lVfDWmTykZf'
}

# ── ReelShort (com.crazymaple.reelshort v3.8.00) ────────────────────
REELSHORT_API_BASE     = "https://d1k8g7qaebqd28.cloudfront.net"
REELSHORT_FALLBACK_URL = "https://v-api.crazymaplestudios.com"
REELSHORT_HEADERS = {
    'User-Agent': 'okhttp/4.12.0',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Connection': 'keep-alive',
}
