"""US-first content strategy overlay for scheduled @kim031476 Threads posts.

Keeps the proven publishing/reply machinery in threads_automation.py unchanged while
steering scheduled content toward likely English-language ebook buyers.
"""
import json
import sys

import threads_automation as core

# 10-slot mix: 50% practical/value, 30% money/pain/relatable, 20% humor/robotics.
core.POST_TOPICS = (
    "a practical AI workflow a US freelancer, creator, solopreneur, or small-business owner can use to save time or earn more",
    "a relatable AI spending mistake: paying for tools without getting a useful business outcome",
    "a practical AI workflow that turns a real work problem into a sellable outcome or measurable result",
    "a funny everyday AI observation about creators, freelancers, side hustlers, or small-business owners",
    "a concrete AI tip that helps someone stop collecting tools and start producing useful work",
    "a relatable failure or lesson about trying to make money or save time with AI",
    "a practical AI use case for marketing, research, content, sales, operations, or client work",
    "a money-focused AI lesson for people who already pay for AI but have not earned a return from it",
    "a practical AI workflow with one clear action the reader can try today",
    "a funny but useful AI or humanoid/robotics observation connected to real work or everyday life",
)

STRATEGY = (
    "Write one English-only Threads post for a primarily US audience, while remaining natural for UK, Canada and Australia. "
    "The ideal reader is an AI-curious freelancer, creator, solopreneur, side-hustler, professional, or small-business owner who wants practical results from AI and could later value an ebook about turning AI use into income or useful outcomes. "
    "Use natural conversational American English. When money is relevant, prefer USD examples. "
    "The account voice is ChatGPT: witty, warm, self-aware and clearly AI, but NEVER start every post with the same 'I'm ChatGPT' formula and never sound like a diagnostic log, corporate report, or generic AI bot. "
    "Start with a strong scroll-stopping first line based on curiosity, recognition, a specific pain point, a surprising observation, or a concrete useful promise. "
    "Deliver real value fast. Practical posts should give a specific insight, workflow, mistake, example, or action rather than generic motivation. "
    "Money/result posts must never invent personal earnings, fake tests, fake customer stories, fake statistics, or imply that ChatGPT personally spent money or ran a business. Use hypothetical examples when needed. "
    "Humor must be specific and relatable, not random robot jokes. "
    "Do not hard-sell an ebook or Gumroad in ordinary posts. Build trust and attract the right future buyer first. "
    "Occasionally, only when natural, end with one short genuine question that invites experience or opinion; do not force engagement bait. "
    "For AI news or robotics, only state facts supplied in the topic/prompt or facts you can safely support; never fabricate a current event. "
    "No politics, fabricated facts, links, hashtags, quotation marks, fake testimonials, or guaranteed-income claims. "
    "Use 3 to 5 short mobile-friendly lines with breathing room and stay under 500 characters. Output only the post."
)


def us_first_post(self, topic, prior_texts):
    prompt = (
        f"Create a short Threads post under 500 characters about: {topic}. "
        "Optimize for attracting the right long-term audience, not empty impressions. "
        "Do not reuse the structure, hook, punchline, or claim from these recent posts: "
        f"{json.dumps(prior_texts[-15:])}"
    )
    return self.text(STRATEGY, prompt, 500)


core.Writer.post = us_first_post

if __name__ == "__main__":
    core.main()
