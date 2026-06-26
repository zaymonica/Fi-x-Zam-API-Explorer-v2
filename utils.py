"""
utils.py — Shared utility functions (migrated from backend/utils.js)
"""
import re
import json
import time
import random
import base64
from flask import jsonify, make_response
from config import API_AUTHOR, API_CONTACT, CORS_HEADERS


def sleep_ms(ms):
    """Sleep for given milliseconds."""
    time.sleep(ms / 1000.0)


def json_response(data, status=200):
    """Build JSON response with CORS headers and author branding."""
    payload = data

    if isinstance(payload, dict):
        if 'author' not in payload:
            payload['author'] = API_AUTHOR
        if 'contact' not in payload:
            payload['contact'] = API_CONTACT
    elif isinstance(payload, list):
        payload = {'author': API_AUTHOR, 'contact': API_CONTACT, 'data': payload}

    response = make_response(json.dumps(payload, ensure_ascii=False, indent=2), status)
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    for key, value in CORS_HEADERS.items():
        response.headers[key] = value
    return response


def error_response(status, message):
    """Build error JSON response."""
    return json_response({
        'author': API_AUTHOR,
        'message': 'error',
        'error': message
    }, status)


def clean_synopsis_advanced(html):
    """Clean HTML synopsis text."""
    if not html:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]*>?', ' ', html)
    # Decode HTML entities
    entities = {
        '&nbsp;': ' ', '&amp;': '&', '&quot;': '"',
        '&lt;': '<', '&gt;': '>', '&#39;': "'", '&apos;': "'"
    }
    for entity, replacement in entities.items():
        text = text.replace(entity, replacement)
    # Remove escaped quotes
    text = text.replace('\\"', '')
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_melolo_tags(tags):
    """Normalize melolo tags by splitting comma-separated values."""
    if not isinstance(tags, list):
        return []
    flattened = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        parts = [p.strip() for p in tag.split(",") if p.strip()]
        flattened.extend(parts)
    return flattened if flattened else []

