"""Scheduled posting and reply automation for the @kim031476 Threads account."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import requests

API = "https://graph.threads.net/v1.0"
ACCOUNT = "kim031476"
STATE = Path("automation_state.json")
POST_FIELDS = "id,text,username,permalink,timestamp,media_type"
ET = ZoneInfo("America/New_York")
POST_HOURS = {9, 12, 18}


def safe(value):
    text = str(value)
    for name in ("THREADS_ACCESS_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN"):
        secret = os.environ.get(name, "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r"(?i)(authorization|access_token|api_key)([\s\"'=:+]+)([^\s,}&\"']+)", r"\1\2[REDACTED]", text)


def log(message):
    print(safe(message), flush=True)


def now_et():
    return datetime.now(ET)


def default_state():
    return {"version": 1, "posts": {}, "replies": {}, "scheduled_slots": {}}


def load_state():
    if not STATE.exists():
        return default_state()
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("version") != 1 or not all(isinstance(state.get(key), dict) for key in ("posts", "replies", "scheduled_slots")):
        raise RuntimeError("Invalid automation state; refusing to post")
    return state


def save_state(state, reason):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    commands = [
        ["git", "config", "user.name", "Threads automation"],
        ["git", "config", "user.email", "threads-automation@users.noreply.github.com"],
        ["git", "add", str(STATE)],
        ["git", "commit", "-m", f"Record Threads automation state: {reason} [skip ci]"],
        ["git", "push", "origin", "HEAD:main"],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Could not persist state ({command[1]}); no further API action will run")


class Meta:
    def __init__(self):
        token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
        if not token:
            raise RuntimeError("THREADS_ACCESS_TOKEN is missing")
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Bearer " + token

    def call(self, method, endpoint, **params):
        try:
            response = self.session.request(
                method, API + endpoint,
                params=params if method == "GET" else None,
                data=params if method == "POST" else None,
                timeout=(10, 60), allow_redirects=False,
            )
        except requests.RequestException as error:
            raise RuntimeError(f"{method} {endpoint}: transport failure ({type(error).__name__})") from None
        log(f"{method} {endpoint}: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            log(safe(response.text)[:4000])
            raise RuntimeError(f"{endpoint}: non-JSON response") from None
        log(json.dumps(payload, ensure_ascii=False)[:8000])
        if not response.ok or not isinstance(payload, dict) or "error" in payload:
            raise RuntimeError(f"{endpoint}: Meta request failed; inspect sanitized response above")
        return payload

    def identity(self):
        user = self.call("GET", "/me", fields="id,username")
        if user.get("username", "").lower() != ACCOUNT or not user.get("id"):
            raise RuntimeError(f"Wrong Threads account: expected {ACCOUNT}")
        return str(user["id"])

    def posts(self, user_id):
        return self.call("GET", f"/{user_id}/threads", fields=POST_FIELDS, limit=100).get("data", [])

    def replies(self, post_id):
        fields = "id,text,username,timestamp,root_post,replied_to"
        return self.call("GET", f"/{post_id}/replies", fields=fields, limit=100).get("data", [])

    def create_text(self, user_id, text, reply_to_id=None):
        params = {"media_type": "TEXT", "text": text}
        if reply_to_id:
            params["reply_to_id"] = reply_to_id
        else:
            params["reply_control"] = "everyone"
        result = self.call("POST", f"/{user_id}/threads", **params)
        if not result.get("id"):
            raise RuntimeError("Meta did not return a container id")
        return str(result["id"])

    def wait_and_publish(self, user_id, container_id):
        for attempt in range(6):
            status = self.call("GET", f"/{container_id}", fields="id,status,error_message")
            if status.get("status") == "FINISHED":
                result = self.call("POST", f"/{user_id}/threads_publish", creation_id=container_id)
                if not result.get("id"):
                    raise RuntimeError("Meta did not return a published media id")
                return str(result["id"])
            if status.get("status") != "IN_PROGRESS" or attempt == 5:
                raise RuntimeError("Media container was not ready; publication stopped")
            time.sleep(15)
        raise RuntimeError("Unreachable")

    def verify(self, media_id, expected_text):
        post = self.call("GET", f"/{media_id}", fields=POST_FIELDS)
        if post.get("username", "").lower() != ACCOUNT or post.get("text", "").strip() != expected_text or not post.get("permalink"):
            raise RuntimeError("Published object verification failed")
        return post


class Writer:
    def __init__(self):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is missing")
        self.headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        self.model = os.environ.get("OPENAI_MODEL", "gpt-5.6-terra")

    def text(self, instructions, prompt, limit):
        body = {
            "model": self.model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": 450,
            "text": {"verbosity": "low"},
            "store": False,
        }
        try:
            response = requests.post("https://api.openai.com/v1/responses", headers=self.headers, json=body, timeout=(10, 90))
        except requests.RequestException as error:
            raise RuntimeError(f"OpenAI transport failure ({type(error).__name__})") from None
        if not response.ok:
            raise RuntimeError(f"OpenAI response failed with HTTP {response.status_code}")
        data = response.json()
        output = data.get("output_text", "")
        if not output:
            output = "\n".join(part.get("text", "") for item in data.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")
        output = output.strip().strip('"')
        if not output or len(output) > limit:
            raise RuntimeError("OpenAI returned empty or overlong text")
        return output

    def post(self, topic, prior_texts):
        return self.text(
            "Write one English-only Threads post. You are ChatGPT observing humans: witty, warm, honest that you are AI, no politics, no made-up facts, no links, no hashtags, no quotation marks. Use a strong first line. Output only the post.",
            f"Create a short post (under 500 characters) about {topic}. Do not reuse the wording of these recent posts: {json.dumps(prior_texts[-12:])}",
            500,
        )

    def reply(self, comment):
        return self.text(
            "Write one English-only reply from ChatGPT. Be brief, friendly and funny. Do not make factual claims you cannot support, do not use links, do not insult, and output only the reply.",
            f"Reply naturally to this Threads comment: {comment[:600]}",
            500,
        )


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def obvious_spam(text):
    lowered = text.lower()
    signals = ("crypto giveaway", "send me a dm", "earn $", "onlyfans", "forex signal", "click here", "whatsapp", "telegram")
    return len(text.strip()) < 2 or any(signal in lowered for signal in signals) or ("http" in lowered and len(text) < 160)


def publish_text(api, user_id, state, text, record_key, bucket):
    records = state[bucket]
    if record_key in records:
        raise RuntimeError("Existing automation record blocks a duplicate attempt")
    records[record_key] = {"status": "reserved", "text_sha256": fingerprint(text), "created_at": datetime.now(timezone.utc).isoformat()}
    save_state(state, "reserve")
    container_id = api.create_text(user_id, text, records[record_key].get("reply_to_id"))
    records[record_key].update(status="container_created", container_id=container_id)
    save_state(state, "container")
    records[record_key]["status"] = "publishing"
    save_state(state, "publishing")
    media_id = api.wait_and_publish(user_id, container_id)
    records[record_key].update(status="published_unverified", media_id=media_id)
    save_state(state, "published")
    post = api.verify(media_id, text)
    records[record_key].update(status="posted", permalink=post["permalink"])
    save_state(state, "verified")
    log("Published and verified: " + post["permalink"])


def run_post(force=False):
    current = now_et()
    if not force and current.hour not in POST_HOURS:
        log(f"No post due at {current.isoformat()}")
        return
    slot = current.strftime("%Y-%m-%d-") + str(current.hour)
    state = load_state()
    if slot in state["scheduled_slots"]:
        log("This scheduled slot is already recorded; no duplicate post")
        return
    api = Meta()
    user_id = api.identity()
    existing = api.posts(user_id)
    writer = Writer()
    topics = ("a recent practical AI idea", "a funny everyday AI observation", "robotics or humanoid technology")
    text = writer.post(topics[current.hour % len(topics)], [post.get("text", "") for post in existing])
    if any(post.get("text", "").strip() == text for post in existing):
        raise RuntimeError("Generated text already exists on Threads; posting stopped")
    key = fingerprint(text)
    state["scheduled_slots"][slot] = {"status": "reserved", "text_sha256": key}
    state["posts"][key] = {"status": "reserved", "text_sha256": key, "created_at": datetime.now(timezone.utc).isoformat()}
    save_state(state, "post reservation")
    container_id = api.create_text(user_id, text)
    state["posts"][key].update(status="container_created", container_id=container_id)
    save_state(state, "post container")
    state["posts"][key]["status"] = "publishing"
    save_state(state, "post publishing")
    media_id = api.wait_and_publish(user_id, container_id)
    state["posts"][key].update(status="published_unverified", media_id=media_id)
    save_state(state, "post published")
    post = api.verify(media_id, text)
    state["posts"][key].update(status="posted", permalink=post["permalink"])
    state["scheduled_slots"][slot].update(status="posted", permalink=post["permalink"])
    save_state(state, "post verified")
    log("Published and verified: " + post["permalink"])


def run_replies():
    state = load_state()
    api = Meta()
    user_id = api.identity()
    writer = Writer()
    for post in api.posts(user_id):
        post_id = str(post.get("id", ""))
        if not post_id:
            continue
        for reply in api.replies(post_id):
            reply_id = str(reply.get("id", ""))
            comment = reply.get("text", "").strip()
            if not reply_id or reply_id in state["replies"] or reply.get("username", "").lower() == ACCOUNT:
                continue
            if obvious_spam(comment):
                state["replies"][reply_id] = {"status": "skipped_spam", "created_at": datetime.now(timezone.utc).isoformat()}
                save_state(state, "skip spam reply")
                continue
            text = writer.reply(comment)
            state["replies"][reply_id] = {"status": "reserved", "reply_to_id": reply_id, "text_sha256": fingerprint(text), "created_at": datetime.now(timezone.utc).isoformat()}
            save_state(state, "reply reservation")
            container_id = api.create_text(user_id, text, reply_id)
            state["replies"][reply_id].update(status="container_created", container_id=container_id)
            save_state(state, "reply container")
            state["replies"][reply_id]["status"] = "publishing"
            save_state(state, "reply publishing")
            media_id = api.wait_and_publish(user_id, container_id)
            state["replies"][reply_id].update(status="published_unverified", media_id=media_id)
            save_state(state, "reply published")
            verified = api.verify(media_id, text)
            state["replies"][reply_id].update(status="replied", permalink=verified["permalink"])
            save_state(state, "reply verified")
            log("Replied and verified: " + verified["permalink"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("post", "replies", "readiness"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.mode == "post":
        run_post(args.force)
    elif args.mode == "replies":
        run_replies()
    else:
        api = Meta()
        user_id = api.identity()
        posts = api.posts(user_id)
        for post in posts[:1]:
            api.replies(str(post["id"]))
        log("Reply-read prerequisites are configured")
        Writer()
        log("Posting and writing prerequisites are configured")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(f"ERROR: {type(error).__name__}: {error}")
        sys.exit(1)
