"""Approval-only Threads publisher. Ambiguous publications are never retried."""
import argparse
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
import requests
from PIL import Image

API = "https://graph.threads.net/v1.0"
ACCOUNT = "kim031476"
HISTORY = Path("posted_history.json")
FIELDS = "id,text,username,media_type,permalink,timestamp"


def safe(value):
    text = str(value)
    for name in ("THREADS_ACCESS_TOKEN", "GITHUB_TOKEN", "META_APP_SECRET"):
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r'(?i)(access_token|client_secret|authorization|password)([\s\"\x27:=]+)([^\s,}&\"\x27]+)', r'\1\2[REDACTED]', text)


def log(value):
    print(safe(value), flush=True)


class Meta:
    def __init__(self):
        token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
        if not token:
            raise RuntimeError("THREADS_ACCESS_TOKEN is missing")
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Bearer " + token

    def call(self, method, endpoint, **params):
        try:
            response = self.session.request(method, API + endpoint,
                params=params if method == "GET" else None,
                data=params if method == "POST" else None,
                timeout=(10, 60), allow_redirects=False)
        except requests.RequestException as exc:
            raise RuntimeError(f"{method} {endpoint}: transport failure ({type(exc).__name__}); outcome may be unknown") from None
        log(f"{method} {endpoint}: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            log(safe(response.text)[:6000])
            raise RuntimeError(f"{endpoint}: non-JSON response") from None
        log(safe(json.dumps(data, ensure_ascii=False))[:12000])
        if not response.ok or not isinstance(data, dict) or "error" in data:
            raise RuntimeError(f"{endpoint}: Meta request failed (HTTP {response.status_code}); see sanitized response")
        return data

    def identity(self):
        user = self.call("GET", "/me", fields="id,username")
        if user.get("username", "").lower() != ACCOUNT or not user.get("id"):
            raise RuntimeError(f"Wrong Threads account: expected {ACCOUNT}; posting blocked")
        return user["id"]


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment or parts.port not in (None, 443):
        raise ValueError("Image URL must be public HTTPS without credentials, fragment, or custom port")
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError("Image URL must resolve only to public IP addresses")


def validate_image(url):
    validate_url(url)
    with requests.get(url, timeout=(10, 30), stream=True, allow_redirects=False) as response:
        mime = response.headers.get("Content-Type", "").split(";")[0].lower()
        length = response.headers.get("Content-Length")
        log(f"Image preflight: HTTP {response.status_code}; type={mime}; content-length={length}")
        if response.status_code != 200 or mime != "image/jpeg":
            raise ValueError("Image must return HTTP 200 and image/jpeg directly")
        if length and int(length) > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MB")
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("Image exceeds 8 MB")
    if not content:
        raise ValueError("Empty image")
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        if image.format != "JPEG" or not 320 <= width <= 1440 or not 0.01 <= width / height <= 10:
            raise ValueError("Invalid JPEG dimensions: expected width 320-1440 and aspect ratio 0.01-10")
        image.verify()
    with Image.open(io.BytesIO(content)) as image:
        image.load()
    log(f"Valid JPEG: {width}x{height}, {len(content)} bytes (Meta fetch still requires API confirmation)")
    return hashlib.sha256(content).hexdigest()


def read_draft():
    text = Path("approved_post.txt").read_text(encoding="utf-8-sig").strip()
    url = Path("approved_image_url.txt").read_text(encoding="utf-8-sig").strip()
    if not text or len(text) > 500:
        raise ValueError("Post text must be 1-500 characters")
    if not url:
        raise ValueError("Approved image URL is required")
    return text, url


def draft_hash(text, url):
    return hashlib.sha256(json.dumps([text, url], ensure_ascii=False).encode()).hexdigest()


def save(history):
    HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Persist BEFORE any irreversible API call; failed push means no publication.
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Live publishing is restricted to GitHub Actions")
    for args in (["git", "add", "posted_history.json"],
                 ["git", "commit", "-m", "Record Threads publication state [skip ci]"],
                 ["git", "push", "origin", "HEAD:main"]):
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"State persistence failed at {args[1]}; posting stopped")


def verify(api, media_id, text=None):
    result = api.call("GET", "/" + str(media_id), fields=FIELDS)
    if str(result.get("id")) != str(media_id) or result.get("username", "").lower() != ACCOUNT or not result.get("permalink"):
        raise RuntimeError("Published object identity/permalink verification failed")
    if text is not None and (result.get("text", "").strip() != text or result.get("media_type") != "IMAGE"):
        raise RuntimeError("Published text or image does not match approved draft")
    return result


def recent_posts(api, user_id):
    result = []
    after = None
    # Do not follow token-bearing paging URLs.
    for _ in range(20):
        params = {"fields": FIELDS, "limit": 100}
        if after:
            params["after"] = after
        page = api.call("GET", f"/{user_id}/threads", **params)
        result.extend(page.get("data", []))
        paging = page.get("paging", {})
        if not paging.get("next"):
            return result
        after = paging.get("cursors", {}).get("after")
        if not after:
            raise RuntimeError("Cannot safely paginate existing posts")
    raise RuntimeError("Too many existing posts to safely check duplicates")


def publish(api, user_id, text, url, image_sha):
    approval = json.loads(Path("publish_approval.json").read_text(encoding="utf-8"))
    fingerprint = draft_hash(text, url)
    if approval.get("status") != "approved" or approval.get("account") != ACCOUNT or approval.get("draft_sha256") != fingerprint or approval.get("image_sha256") != image_sha:
        raise RuntimeError("Missing approval for this exact text, URL, image bytes, and account")
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    if not isinstance(history, dict) or history.get("version") != 1 or not isinstance(history.get("posts"), dict):
        raise RuntimeError("Invalid history; posting blocked")
    previous = history["posts"].get(fingerprint)
    if previous:
        if previous.get("publish_id"):
            obj = verify(api, previous["publish_id"], text)
            log("Already published; no new post: " + obj["permalink"])
            if previous.get("status") != "posted":
                previous.update(status="posted", permalink=obj["permalink"])
                save(history)
            return
        raise RuntimeError("Existing in-flight/failed attempt: reconcile it before retrying; duplicate blocked")
    for item in recent_posts(api, user_id):
        if item.get("text", "").strip() == text:
            raise RuntimeError("Matching text already exists on Threads; review existing permalink before posting")
    entry = {"status": "reserved", "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
             "image_url": url, "image_sha256": image_sha,
             "timestamp": datetime.now(timezone.utc).isoformat(), "run_id": os.environ.get("GITHUB_RUN_ID")}
    history["posts"][fingerprint] = entry
    save(history)
    creation = api.call("POST", f"/{user_id}/threads", media_type="IMAGE", image_url=url, text=text)
    creation_id = creation.get("id")
    if not creation_id:
        raise RuntimeError("No container ID; inspect reserved attempt")
    entry.update(status="container_created", creation_id=creation_id)
    save(history)
    for attempt in range(6):
        status = api.call("GET", f"/{creation_id}", fields="id,status,error_message")
        if status.get("status") == "FINISHED":
            break
        if status.get("status") != "IN_PROGRESS" or attempt == 5:
            raise RuntimeError("Container is not ready; publication stopped")
        time.sleep(60)
    entry["status"] = "publishing"
    save(history)
    published = api.call("POST", f"/{user_id}/threads_publish", creation_id=creation_id)
    media_id = published.get("id")
    if not media_id:
        raise RuntimeError("No publish ID; outcome unknown, do not retry")
    entry.update(status="published_unverified", publish_id=media_id)
    save(history)
    obj = verify(api, media_id, text)
    entry.update(status="posted", permalink=obj["permalink"])
    save(history)
    log(f"Published and verified Threads post id: {media_id}\nPermalink: {obj['permalink']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["validate", "diagnose", "publish"], default="validate", nargs="?")
    args = parser.parse_args()
    text, url = read_draft()
    image_sha = validate_image(url)
    log("Draft SHA256: " + draft_hash(text, url))
    log("Image SHA256: " + image_sha)
    if args.mode == "validate":
        return
    api = Meta()
    user_id = api.identity()
    if args.mode == "diagnose":
        recent_posts(api, user_id)
        verify(api, "17965602573193805")
    else:
        publish(api, user_id, text, url, image_sha)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
