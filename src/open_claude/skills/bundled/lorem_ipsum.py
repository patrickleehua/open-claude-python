"""Lorem Ipsum skill - generate filler text for long context testing.

Port of Claude-Code-rev/src/skills/bundled/loremIpsum.ts
"""

from __future__ import annotations

import random

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition, is_ant_user

# Verified 1-token words (tested via API token counting)
ONE_TOKEN_WORDS = [
    "the", "a", "an", "I", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its", "our",
    "this", "that", "what", "who",
    "is", "are", "was", "were", "be", "been", "have", "has", "had",
    "do", "does", "did", "will", "would", "can", "could", "may", "might",
    "must", "shall", "should", "make", "made", "get", "got", "go", "went",
    "come", "came", "see", "saw", "know", "take", "think", "look", "want",
    "use", "find", "give", "tell", "work", "call", "try", "ask", "need",
    "feel", "seem", "leave", "put",
    "time", "year", "day", "way", "man", "thing", "life", "hand", "part",
    "place", "case", "point", "fact", "good", "new", "first", "last",
    "long", "great", "little", "own", "other", "old", "right", "big",
    "high", "small", "large", "next", "early", "young", "few", "public",
    "bad", "same", "able",
    "in", "on", "at", "to", "for", "of", "with", "from", "by", "about",
    "like", "through", "over", "before", "between", "under", "since",
    "without", "and", "or", "but", "if", "than", "because", "as", "until",
    "while", "so", "though", "both", "each", "when", "where", "why", "how",
    "not", "now", "just", "more", "also", "here", "there", "then", "only",
    "very", "well", "back", "still", "even", "much", "too", "such",
    "never", "again", "most", "once", "off", "away", "down", "out", "up",
    "test", "code", "data", "file", "line", "text", "word", "number",
    "system", "program", "set", "run", "value", "name", "type", "state",
    "end", "start",
]


def _generate_lorem_ipsum(target_tokens: int) -> str:
    """Generate random sentences to approximately fill the requested token count."""
    tokens = 0
    result = ""

    while tokens < target_tokens:
        sentence_length = 10 + random.randint(0, 10)

        for i in range(sentence_length):
            if tokens >= target_tokens:
                break
            word = random.choice(ONE_TOKEN_WORDS)
            result += word
            tokens += 1

            if i == sentence_length - 1 or tokens >= target_tokens:
                result += ". "
            else:
                result += " "

        # Paragraph break roughly 20% chance
        if random.random() < 0.2 and tokens < target_tokens:
            result += "\n\n"

    return result.strip()


async def _get_prompt(args: str, context: object) -> list[dict]:
    parsed = int(args) if args and args.strip().isdigit() else 0

    if args and (not args.strip().isdigit() or parsed <= 0):
        return [
            {
                "type": "text",
                "text": "Invalid token count. Please provide a positive number (e.g., /lorem-ipsum 10000).",
            }
        ]

    target_tokens = parsed or 10000

    # Cap at 500k tokens for safety
    capped_tokens = min(target_tokens, 500_000)

    if capped_tokens < target_tokens:
        return [
            {
                "type": "text",
                "text": f"Requested {target_tokens} tokens, but capped at 500,000 for safety.\n\n{_generate_lorem_ipsum(capped_tokens)}",
            }
        ]

    return [{"type": "text", "text": _generate_lorem_ipsum(capped_tokens)}]


def register_lorem_ipsum_skill() -> None:
    if not is_ant_user():
        return

    register_bundled_skill(
        BundledSkillDefinition(
            name="lorem-ipsum",
            description="Generate filler text for long context testing. Specify token count as argument (e.g., /lorem-ipsum 50000). Outputs approximately the requested number of tokens. Ant-only.",
            argument_hint="[token_count]",
            user_invocable=True,
            get_prompt_for_command=_get_prompt,
        )
    )
