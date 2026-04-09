"""Loop skill - schedule recurring prompts via cron.

Port of Claude-Code-rev/src/skills/bundled/loop.ts

Deferred: registered but disabled until CronCreate/CronDelete tools are implemented.
"""

from __future__ import annotations

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition

DEFAULT_INTERVAL = "10m"

CRON_CREATE_TOOL_NAME = "CronCreate"
CRON_DELETE_TOOL_NAME = "CronDelete"
DEFAULT_MAX_AGE_DAYS = 7

USAGE_MESSAGE = f"""Usage: /loop [interval] <prompt>

Run a prompt or slash command on a recurring interval.

Intervals: Ns, Nm, Nh, Nd (e.g. 5m, 30m, 2h, 1d). Minimum granularity is 1 minute.
If no interval is specified, defaults to {DEFAULT_INTERVAL}.

Examples:
  /loop 5m /babysit-prs
  /loop 30m check the deploy
  /loop 1h /standup 1
  /loop check the deploy          (defaults to {DEFAULT_INTERVAL})
  /loop check the deploy every 20m"""


def _build_prompt(args: str) -> str:
    return f"""# /loop — schedule a recurring prompt

Parse the input below into `[interval] <prompt…>` and schedule it with {CRON_CREATE_TOOL_NAME}.

## Parsing (in priority order)

1. **Leading token**: if the first whitespace-delimited token matches `^\\d+[smhd]$` (e.g. `5m`, `2h`), that's the interval; the rest is the prompt.
2. **Trailing "every" clause**: otherwise, if the input ends with `every <N><unit>` or `every <N> <unit-word>` (e.g. `every 20m`, `every 5 minutes`, `every 2 hours`), extract that as the interval and strip it from the prompt.
3. **Default**: otherwise, interval is `{DEFAULT_INTERVAL}` and the entire input is the prompt.

If the resulting prompt is empty, show usage and stop — do not call {CRON_CREATE_TOOL_NAME}.

## Interval → cron

Supported suffixes: `s` (seconds, rounded up to nearest minute, min 1), `m` (minutes), `h` (hours), `d` (days).

| Interval pattern      | Cron expression     | Notes                                    |
|-----------------------|---------------------|------------------------------------------|
| `Nm` where N ≤ 59    | `*/N * * * *`      | every N minutes                          |
| `Nm` where N ≥ 60    | `0 */H * * *`      | round to hours (H = N/60, must divide 24)|
| `Nh` where N ≤ 23    | `0 */N * * *`      | every N hours                            |
| `Nd`                 | `0 0 */N * *`      | every N days at midnight local           |
| `Ns`                 | treat as `ceil(N/60)m` | cron minimum granularity is 1 minute  |

## Action

1. Call {CRON_CREATE_TOOL_NAME} with:
   - `cron`: the expression from the table above
   - `prompt`: the parsed prompt, verbatim
   - `recurring`: `true`
2. Briefly confirm: what's scheduled, the cron expression, the cadence, auto-expire after {DEFAULT_MAX_AGE_DAYS} days, cancel with {CRON_DELETE_TOOL_NAME}.
3. **Then immediately execute the parsed prompt now**.

## Input

{args}"""


async def _get_prompt(args: str, context: object) -> list[dict]:
    trimmed = args.strip()
    if not trimmed:
        return [{"type": "text", "text": USAGE_MESSAGE}]
    return [{"type": "text", "text": _build_prompt(trimmed)}]


def register_loop_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="loop",
            description=f"Run a prompt or slash command on a recurring interval (e.g. /loop 5m /foo, defaults to {DEFAULT_INTERVAL})",
            when_to_use=(
                "When the user wants to set up a recurring task, poll for status, "
                "or run something repeatedly on an interval. Do NOT invoke for one-off tasks."
            ),
            argument_hint="[interval] <prompt>",
            user_invocable=True,
            is_enabled=lambda: False,  # Disabled until cron tools exist
            get_prompt_for_command=_get_prompt,
        )
    )
