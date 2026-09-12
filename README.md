# Threads posting for @kim031476

This repository runs in GitHub Actions. The laptop does not need to stay on after a workflow starts.

## Verified on 2026-09-12

- The existing token belongs to `kim031476` (user ID `38433404592940606`).
- The earlier text post exists: https://www.threads.com/@kim031476/post/DdLEPAUFUqj
- The original `public/tiangong.jpg` lacked its JPEG end-of-image marker (`FF D9`). Its header and `Image.verify()` passed, but full pixel decoding failed. Restoring the missing two-byte marker fixes decoding without changing the compressed image data.
- GitHub serves the repaired JPEG as HTTP 200, `image/jpeg`, 7,493 bytes, 384 x 384.
- The historical HTTP 500 log does not contain Meta's error response, so the missing JPEG marker is a confirmed defect and likely cause, not proof of the historical Meta-side cause.
- New diagnostics verify identity and retrieve the old post successfully. No image post has yet been published by the repaired implementation.

## Test and diagnose

1. Open Actions > Threads diagnostics > Run workflow > main.
2. The job runs 10 safety tests, validates the complete image, checks `GET /me`, lists existing posts, and verifies the earlier published ID and permalink.
3. A failure remains a failed GitHub job and prints sanitized endpoint, status, and response details. Tokens are never intentionally printed.

Locally, install `requirements.txt`, then run:

```sh
python -m unittest discover -s tests -v
python post_threads.py validate
```

`validate` needs no token and does not publish. `diagnose` uses `THREADS_ACCESS_TOKEN` and makes only GET calls to Meta. The no-argument script defaults to validation, so the old workflows cannot accidentally publish while deployment is being completed.

## Publishing safeguards implemented in Python

Live publishing is restricted to GitHub Actions and requires an exact approval in `publish_approval.json`: `status`, `account`, `draft_sha256`, and `image_sha256`. The hashes are printed by validation. Text and URL come from the existing approved files; the image bytes must also match the approval.

A version-1 `posted_history.json` stores a map named `posts`, keyed by draft hash. Before creating a container, the publisher commits and pushes a reservation. Before publication, it pushes a `publishing` record. It records the published ID before verifying the object's account, caption, image type, and permalink. Failed state persistence stops the next API mutation. A reserved or ambiguous attempt blocks retries; it does not blindly create another post. A known published ID can be verified again without reposting.

A serialized manual workflow and repository write permission are still required to activate this path. They are awaiting owner confirmation. Do not invoke `publish` using the old workflow, do not delete ambiguous history records just to retry, and do not enable scheduled posts yet.

## Recovery

- If image validation or account verification fails, no container was created.
- If a reservation exists without a container ID, inspect the sanitized API response. Container creation alone is not publication, but do not clear the reservation without checking the workflow and account.
- If a container ID exists, query its `status,error_message`. A `publishing` state can mean the publish request succeeded even when the HTTP response was lost. Reconcile using the account's posts and the container status; never blindly resend `threads_publish`.
- If a publish ID exists, verify it and update the state; never recreate it merely because verification temporarily failed.
- Existing text exactly matching a draft blocks another post even if the earlier post had no image. The owner must choose how to handle the existing post first.

## API references

Meta's official collection documents image containers with a public `image_url`, followed by publication, container status checks, and media retrieval:
https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api
https://developers.facebook.com/docs/threads/posts

No three-times-daily schedule or automatic replies are enabled. Approval for recurring publishing and additional reply permissions remain separate future steps.
