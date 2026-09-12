import os
import requests

TOKEN = os.environ.get("THREADS_ACCESS_TOKEN")
API = "https://graph.threads.net/v1.0"


def publish_post(text: str, image_url: str | None = None):
    if not TOKEN:
        raise RuntimeError("THREADS_ACCESS_TOKEN is missing")
    if not text or len(text) > 500:
        raise ValueError("Post text must be 1-500 characters")

    payload = {
        "text": text,
        "access_token": TOKEN,
    }

    if image_url:
        payload.update({
            "media_type": "IMAGE",
            "image_url": image_url,
        })
    else:
        payload["media_type"] = "TEXT"

    create = requests.post(
        f"{API}/me/threads",
        data=payload,
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
    publish_post(
        os.environ.get("POST_TEXT", ""),
        os.environ.get("POST_IMAGE_URL") or None,
    )
