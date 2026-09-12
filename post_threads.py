import os
import sys
import requests

TOKEN = os.environ.get("THREADS_ACCESS_TOKEN")
API = "https://graph.threads.net/v1.0"


def publish_text(text: str):
    if not TOKEN:
        raise RuntimeError("THREADS_ACCESS_TOKEN is missing")
    if not text or len(text) > 500:
        raise ValueError("Post text must be 1-500 characters")

    create = requests.post(
        f"{API}/me/threads",
        data={
            "media_type": "TEXT",
            "text": text,
            "access_token": TOKEN,
        },
        timeout=30,
    )
    create.raise_for_status()
    creation_id = create.json()["id"]

    publish = requests.post(
        f"{API}/me/threads_publish",
        data={"creation_id": creation_id, "access_token": TOKEN},
        timeout=30,
    )
    publish.raise_for_status()
    print("Published Threads post id:", publish.json().get("id"))


if __name__ == "__main__":
    publish_text(os.environ.get("POST_TEXT", ""))
