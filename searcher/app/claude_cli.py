"""Subprocess wrapper around the Claude Code CLI (`claude -p`).

The searcher never touches the Anthropic SDK: every model call goes through
the CLI so it is billed to the Claude subscription — locally the logged-in
CLI, on a server CLAUDE_CODE_OAUTH_TOKEN. ANTHROPIC_API_KEY is stripped from
the child environment so the CLI cannot silently fall back to API billing.

`--output-format json --json-schema <schema>` makes the CLI print ONE JSON
object whose `structured_output` is already validated against the schema, so
there is no prose parsing here. Proven 2026-09-25: Trek Marlin 5 → 5 real
listings in 34 s.
"""
import json
import logging
import os
import subprocess
import time

from . import config

logger = logging.getLogger("searcher.cli")

TOOLS = "WebSearch,WebFetch"
VERSION_TIMEOUT = 30.0  # `claude --version` is quick; anything longer is a broken install
TAIL_CHARS = 500        # how much of stderr/stdout goes into an ERROR log line


class ClaudeCliError(RuntimeError):
    """The CLI produced no usable structured result.

    str(exc) is a short, sanitised summary ("claude CLI failed: exit 1") that
    is safe to relay to HTTP callers — raw stderr only ever goes to the log.
    """


def _tail(text) -> str:
    """Last TAIL_CHARS of a str/bytes/None stream, for logging."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text.strip()[-TAIL_CHARS:]


# No ANTHROPIC_API_KEY: the CLI must use the subscription (OAuth) login. The
# other two are secrets the CLI (an LLM with network tools, fed user text)
# has no business seeing. CLAUDE_CODE_OAUTH_TOKEN stays — the CLI needs it.
_STRIP_FROM_CHILD = {"ANTHROPIC_API_KEY", "SEARCHER_API_KEY", "DATABASE_URL"}


def _child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _STRIP_FROM_CHILD}


def _parse_stdout(stdout: str) -> dict | None:
    """The CLI's single result object; tolerates stray lines before it."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
            except ValueError:
                continue
    return None


def cli_version() -> str | None:
    """`claude --version` output (e.g. "2.1.282 (Claude Code)"), None when the CLI is unusable."""
    binary = config.claude_binary()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=_child_env(), timeout=VERSION_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("claude --version failed | binary=%s error=%s", binary, exc)
        return None
    if proc.returncode != 0:
        logger.warning("claude --version exit %d | stderr=%r", proc.returncode, _tail(proc.stderr))
        return None
    return proc.stdout.strip() or None


def run_structured(system_prompt: str, user_message: str, schema: dict) -> dict:
    """Run one `claude -p` turn and return its schema-validated `structured_output`.

    Blocking (call it via asyncio.to_thread). The user text is ONE argv
    element — never a shell string. Raises ClaudeCliError with a sanitised
    summary on a missing binary, non-zero exit, timeout, unparseable output
    or a result without `structured_output`; the stderr tail is logged at
    ERROR in every one of those cases.
    """
    binary = config.claude_binary()
    if not binary:
        logger.error("claude CLI not found | CLAUDE_BIN=%r PATH lookup failed", os.getenv("CLAUDE_BIN", ""))
        raise ClaudeCliError("claude CLI not found")

    argv = [
        binary, "-p", user_message,
        "--system-prompt", system_prompt,
        "--output-format", "json",
        "--json-schema", json.dumps(schema, separators=(",", ":")),
        "--tools", TOOLS,
        "--allowedTools", TOOLS,
        "--permission-prompts", "none",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--exclude-dynamic-system-prompt-sections",
        "--model", config.CLAUDE_MODEL,
    ]
    timeout = config.CLI_TIMEOUT
    logger.info("claude CLI start | model=%s timeout=%.0fs message=%r", config.CLAUDE_MODEL, timeout, user_message)

    t0 = time.perf_counter()
    try:
        # stdin=DEVNULL: with an inherited stdin the CLI waits ~3 s for piped input.
        proc = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=_child_env(), timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error(
            "claude CLI timed out | timeout=%.0fs model=%s stderr_tail=%r",
            timeout, config.CLAUDE_MODEL, _tail(exc.stderr),
        )
        raise ClaudeCliError(f"claude CLI timed out after {timeout:.0f} s") from exc
    except OSError as exc:
        logger.error("claude CLI could not be started | binary=%s error=%s", binary, exc)
        raise ClaudeCliError("claude CLI could not be started") from exc
    elapsed = time.perf_counter() - t0

    if proc.returncode != 0:
        logger.error(
            "claude CLI failed | returncode=%d elapsed=%.2fs stderr_tail=%r stdout_tail=%r",
            proc.returncode, elapsed, _tail(proc.stderr), _tail(proc.stdout),
        )
        raise ClaudeCliError(f"claude CLI failed: exit {proc.returncode}")

    data = _parse_stdout(proc.stdout)
    if data is None:
        logger.error(
            "claude CLI printed no JSON result | elapsed=%.2fs stdout_tail=%r stderr_tail=%r",
            elapsed, _tail(proc.stdout), _tail(proc.stderr),
        )
        raise ClaudeCliError("claude CLI returned unparseable output")

    usage = data.get("usage") or {}
    logger.info(
        "claude CLI done | elapsed=%.2fs subtype=%s num_turns=%s duration_api_ms=%s "
        "input_tokens=%s output_tokens=%s total_cost_usd=%s",
        elapsed, data.get("subtype"), data.get("num_turns"), data.get("duration_api_ms"),
        usage.get("input_tokens"), usage.get("output_tokens"), data.get("total_cost_usd"),
    )

    if data.get("subtype") != "success" or data.get("is_error"):
        logger.error(
            "claude CLI run did not succeed | subtype=%s is_error=%s result_tail=%r stderr_tail=%r",
            data.get("subtype"), data.get("is_error"), _tail(str(data.get("result", ""))), _tail(proc.stderr),
        )
        raise ClaudeCliError(f"claude CLI run ended with {data.get('subtype') or 'an error'}")

    structured = data.get("structured_output")
    if not isinstance(structured, dict):
        logger.error(
            "claude CLI returned no structured output | result_tail=%r stderr_tail=%r",
            _tail(str(data.get("result", ""))), _tail(proc.stderr),
        )
        raise ClaudeCliError("claude CLI returned no structured output")
    return structured
