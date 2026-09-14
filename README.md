# Threads automation for @kim031476

This repository runs independently in GitHub Actions. It controls only the `kim031476` Threads account.

## Active automation

- `Scheduled Threads posts`: creates one English post at 9am, noon, and 6pm in America/New_York. The workflow is scheduled at both possible UTC hours and the Python program selects the correct one, so daylight saving time does not shift the posting time.
- `Threads reply automation`: checks every hour and replies only to new, on-topic questions or substantive opinions. It sends at most five replies per America/New_York calendar day, skips its own comments and obvious promotional/scam messages, and records every handled reply ID so it cannot reply twice.
- `Automation readiness`: makes only read-only checks for the account, recent posts, reply access, and the OpenAI API key.

Both automations use `automation_state.json`. Before a Threads container or publish call, the workflow commits and pushes its state. That reservation, together with GitHub Actions concurrency, prevents duplicate posting if a job is retried or two schedules overlap. Logs redact access tokens and API keys.

## Required GitHub secrets

Open the repository’s **Settings → Secrets and variables → Actions** and verify these secrets exist:

- `THREADS_ACCESS_TOKEN` — must belong to `kim031476` and have `threads_basic`, `threads_content_publish`, `threads_read_replies`, and `threads_manage_replies`.
- `OPENAI_API_KEY` — billed OpenAI API key for writing posts and replies. A ChatGPT subscription alone is not an API key.

The workflows have `contents: write` because they must persist `automation_state.json`. Do not remove that permission.

## First verification

1. In GitHub Actions, run **Automation readiness**. It must finish green before live automation is trusted.
2. Run **Scheduled Threads posts** and leave “Post now” unchecked. Outside a scheduled Eastern Time hour it safely exits without posting.
3. To publish one intentional first automated test post, run **Scheduled Threads posts** with “Post now” checked. The action prints a verified permalink.
4. Then run **Threads reply automation** once. It reads and responds only to new eligible replies; it never reuses an already-recorded reply ID.

## Images

Scheduled posts generate a new square image and make it publicly reachable before publishing. The earlier approved-image publisher remains in `post_threads.py` for manual image posts. Automatic image generation needs a public image host that Meta can fetch; generated image bytes cannot be handed directly to the Threads API. Do not replace the verified posting path with an unhosted local image.

## Existing manual diagnostic

`post_threads.py diagnose` remains read-only and verifies the known account and earlier post. It is separate from the scheduled automation.
