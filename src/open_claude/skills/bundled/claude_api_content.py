"""Claude API content bundle - model vars and file map.

Port of Claude-Code-rev/src/skills/bundled/claudeApiContent.ts
"""

from __future__ import annotations

SKILL_MODEL_VARS = {
    "OPUS_ID": "claude-opus-4-6",
    "OPUS_NAME": "Claude Opus 4.6",
    "SONNET_ID": "claude-sonnet-4-6",
    "SONNET_NAME": "Claude Sonnet 4.6",
    "HAIKU_ID": "claude-haiku-4-5",
    "HAIKU_NAME": "Claude Haiku 4.5",
    "PREV_SONNET_ID": "claude-sonnet-4-5",
}

SKILL_PROMPT = """# Claude API Skill

Build apps with the Claude API or Anthropic SDK.

TRIGGER when: code imports `anthropic`/`@anthropic-ai/sdk`/`claude_agent_sdk`, or user asks to use Claude API, Anthropic SDKs, or Agent SDK.
DO NOT TRIGGER when: code imports `openai`/other AI SDK, general programming, or ML/data-science tasks.

## Quick Reference

**Model IDs:**
- Claude Opus 4.6: `claude-opus-4-6`
- Claude Sonnet 4.6: `claude-sonnet-4-6`
- Claude Haiku 4.5: `claude-haiku-4-5`

## Reading Guide

### Quick Task Reference

**Single text classification/summarization/extraction/Q&A:**
→ Refer to `{lang}/claude-api/README.md`

**Chat UI or real-time response display:**
→ Refer to `{lang}/claude-api/README.md` + `{lang}/claude-api/streaming.md`

**Function calling / tool use / agents:**
→ Refer to `{lang}/claude-api/README.md` + `shared/tool-use-concepts.md` + `{lang}/claude-api/tool-use.md`

**Batch processing:**
→ Refer to `{lang}/claude-api/README.md` + `{lang}/claude-api/batches.md`

**Error handling:**
→ Refer to `shared/error-codes.md`
"""

# SKILL_FILES maps relative paths to markdown content.
# In the TS version these are loaded via Bun's text loader.
# In Python we use placeholder content since the actual docs are in the claude_api/ directory.
SKILL_FILES: dict[str, str] = {
    "python/claude-api/README.md": "# Claude API (Python)\n\nPython SDK for the Claude API.\n\nRestored placeholder content.",
    "python/claude-api/streaming.md": "# Streaming\n\nStreaming responses with the Python SDK.\n\nRestored placeholder content.",
    "python/claude-api/tool-use.md": "# Tool Use\n\nTool use with the Python SDK.\n\nRestored placeholder content.",
    "python/claude-api/batches.md": "# Batches\n\nBatch processing with the Python SDK.\n\nRestored placeholder content.",
    "python/claude-api/files-api.md": "# Files API\n\nFiles API with the Python SDK.\n\nRestored placeholder content.",
    "python/agent-sdk/README.md": "# Agent SDK (Python)\n\nPython Agent SDK.\n\nRestored placeholder content.",
    "python/agent-sdk/patterns.md": "# Agent SDK Patterns\n\nCommon patterns for the Agent SDK.\n\nRestored placeholder content.",
    "typescript/claude-api/README.md": "# Claude API (TypeScript)\n\nTypeScript SDK for the Claude API.\n\nRestored placeholder content.",
    "typescript/claude-api/streaming.md": "# Streaming\n\nStreaming responses with the TypeScript SDK.\n\nRestored placeholder content.",
    "typescript/claude-api/tool-use.md": "# Tool Use\n\nTool use with the TypeScript SDK.\n\nRestored placeholder content.",
    "typescript/claude-api/batches.md": "# Batches\n\nBatch processing with the TypeScript SDK.\n\nRestored placeholder content.",
    "typescript/claude-api/files-api.md": "# Files API\n\nFiles API with the TypeScript SDK.\n\nRestored placeholder content.",
    "typescript/agent-sdk/README.md": "# Agent SDK (TypeScript)\n\nTypeScript Agent SDK.\n\nRestored placeholder content.",
    "typescript/agent-sdk/patterns.md": "# Agent SDK Patterns\n\nCommon patterns for the Agent SDK.\n\nRestored placeholder content.",
    "shared/error-codes.md": "# Error Codes\n\nCommon error codes.\n\nRestored placeholder content.",
    "shared/models.md": "# Models\n\nModel catalog.\n\nRestored placeholder content.",
    "shared/prompt-caching.md": "# Prompt Caching\n\nPrompt caching documentation.\n\nRestored placeholder content.",
    "shared/tool-use-concepts.md": "# Tool Use Concepts\n\nTool use concepts.\n\nRestored placeholder content.",
    "shared/live-sources.md": "# Live Sources\n\nLive documentation sources.\n\nRestored placeholder content.",
    "csharp/claude-api.md": "# Claude API (C#)\n\nC# SDK.\n\nRestored placeholder content.",
    "curl/examples.md": "# cURL Examples\n\ncURL examples.\n\nRestored placeholder content.",
    "go/claude-api.md": "# Claude API (Go)\n\nGo SDK.\n\nRestored placeholder content.",
    "java/claude-api.md": "# Claude API (Java)\n\nJava SDK.\n\nRestored placeholder content.",
    "php/claude-api.md": "# Claude API (PHP)\n\nPHP SDK.\n\nRestored placeholder content.",
    "ruby/claude-api.md": "# Claude API (Ruby)\n\nRuby SDK.\n\nRestored placeholder content.",
}
