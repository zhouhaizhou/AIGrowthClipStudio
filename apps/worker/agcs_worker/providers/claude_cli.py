"""Claude providers that shell out to the local `claude` CLI (Claude Code print mode)
instead of the Anthropic SDK. Useful when access is via a Claude Code subscription
proxy (e.g. reclaude) rather than a raw `ANTHROPIC_API_KEY` — the CLI uses whatever
auth Claude Code is already configured with, so no API key is needed here.

Cost note: each call carries Claude Code's own system-prompt overhead (~10k+ input
tokens). (We deliberately do NOT pass `--bare` — it skips keychain reads, which breaks
reclaude's auth with "Not logged in".) One call per task (highlight) + one per highlight
(packaging); budget accordingly. Set CLAUDE_CLI_BIN to override the binary.
"""
import json as _json
import logging
import os
import subprocess
import tempfile
from typing import List

from .base import HighlightSegment, Packaging
# Reuse the SDK providers' prompt builders + parsing/validation so the CLI path
# stays behaviour-identical (same schema, same grounding/clamping, same fallbacks).
from .llm_highlight import (
    ALLOWED_TYPES, SYSTEM_PROMPT as _HL_SYSTEM, _build_user as _hl_build_user,
    _to_segments,
)
from .llm_packaging import (
    SYSTEM_PROMPT as _PK_SYSTEM, _build_user as _pk_build_user, _to_packaging,
)

_log = logging.getLogger(__name__)


class ClaudeCliError(RuntimeError):
    pass


def _default_runner(prompt: str, model: str, timeout: int) -> str:
    """Run `claude -p <prompt> --output-format json --bare` and return the model text.

    The CLI prints an envelope like {"type":"result","result":"<text>",...}; we return
    the `result` string. Raises ClaudeCliError on non-zero exit / bad envelope / model error.
    """
    binary = os.environ.get("CLAUDE_CLI_BIN", "claude")
    # --strict-mcp-config + no --mcp-config => start zero MCP servers.
    # --setting-sources "" => load NO settings (no hooks/skills/CLAUDE.md), so the nested
    # call behaves as a clean one-shot completion instead of inheriting "always use skills"
    # behaviour (which otherwise makes it over-work the prompt and time out). Run from a
    # neutral cwd for the same reason. reclaude auth (keychain/daemon) is unaffected.
    cmd = [binary, "-p", prompt, "--output-format", "json",
           "--strict-mcp-config", "--setting-sources", ""]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired as e:
        raise ClaudeCliError(f"{binary} -p timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise ClaudeCliError(f"`{binary}` CLI not found on PATH") from e
    if proc.returncode != 0:
        raise ClaudeCliError(f"{binary} -p failed ({proc.returncode}): {proc.stderr[-500:]}")
    try:
        env = _json.loads(proc.stdout)
    except _json.JSONDecodeError as e:
        raise ClaudeCliError(f"{binary} -p returned non-JSON envelope: {proc.stdout[:200]!r}") from e
    if env.get("is_error") or env.get("subtype") not in (None, "success"):
        raise ClaudeCliError(f"{binary} -p reported error: {env.get('result')!r}")
    return env.get("result", "") or ""


def _strip_fences(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]          # drop the ```/```json opening line
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _match_brace(s: str, start: int) -> int:
    """Index of the '}' that closes the '{' at `start`, counting braces (assumes JSON
    string values contain no literal { } — true for our prompts). -1 if unbalanced."""
    depth = 0
    for j in range(start, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _escape_inner_quotes(s: str) -> str:
    """Escape unescaped ASCII double-quotes that appear *inside* a JSON string value.

    Models occasionally hand-write e.g. `"reason":"反复出现"住"字"` — the inner quotes are
    literal, not delimiters. Heuristic: inside a string, a `"` is a closing delimiter only
    if the next non-space char is structural (, : } ]) or EOF; otherwise escape it.
    """
    out = []
    in_str = False
    esc = False
    n = len(s)
    for i, c in enumerate(s):
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
            continue
        if esc:
            out.append(c); esc = False; continue
        if c == "\\":
            out.append(c); esc = True; continue
        if c == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",:}]":
                out.append(c); in_str = False       # real closing delimiter
            else:
                out.append('\\"')                    # literal inner quote -> escape
            continue
        out.append(c)
    return "".join(out)


def _lenient_loads(span: str):
    """json.loads, retrying once after repairing unescaped inner quotes. None on failure."""
    try:
        return _json.loads(span)
    except _json.JSONDecodeError:
        pass
    try:
        return _json.loads(_escape_inner_quotes(span))
    except _json.JSONDecodeError:
        return None


def _extract_json_object(text: str) -> dict:
    """Pull the first parseable JSON object out of model text.

    Tolerates ``` fences, prose before/after, and unescaped inner quotes in Chinese values
    (via _lenient_loads). Tries each '{' so a stray brace in a preamble doesn't abort.
    """
    s = _strip_fences(text)
    i = 0
    while True:
        start = s.find("{", i)
        if start == -1:
            return {}
        end = _match_brace(s, start)
        if end != -1:
            obj = _lenient_loads(s[start:end + 1])
            if isinstance(obj, dict):
                return obj
        i = start + 1


def _run_and_parse(runner, prompt: str, model: str, timeout: int, attempts: int = 2) -> dict:
    """Call the CLI and parse a JSON object, retrying once on a failed/empty parse
    (model output is non-deterministic; a retry usually fixes a stray-prose miss)."""
    for _ in range(max(1, attempts)):
        try:
            text = runner(prompt, model, timeout)
        except ClaudeCliError as e:
            _log.warning("claude -p call failed: %s", e)
            continue
        obj = _extract_json_object(text)
        if obj:
            return obj
        _log.warning("claude -p output did not contain parseable JSON; retrying")
    return {}


# NOTE: unlike the SDK tool_use path, the CLI makes the model hand-write JSON, so we must
# guard valid-JSON-ness in the prompt: no inner ASCII quotes (use 「」), concise fields,
# single-value recommendedScenario.
_JSON_RULES = (
    "\n\n严格只输出一个 JSON 对象本身：不要解释、不要 Markdown、不要代码围栏。"
    "字段值内禁止使用英文双引号(\")，需要引用词语时用中文引号「」。"
)

_HL_INSTRUCTION = (
    _JSON_RULES +
    '格式：{"segments":[{"startMs":<int>,"endMs":<int>,"highlightType":"<枚举>","score":<0~1>,'
    '"reason":"<=40字","summary":"<=30字","recommendedScenario":"<单个场景>","riskLevel":"low|medium|high"}]}'
    "\nhighlightType 只能取其一：" + ", ".join(ALLOWED_TYPES) +
    "。recommendedScenario 必须是单个场景值，不要用逗号拼接。"
)

_PK_INSTRUCTION = (
    _JSON_RULES +
    '格式：{"title":"<=20字","coverText":"<=12字","recommendationText":"<=40字","tags":["...","..."]}'
)


class ClaudeCliHighlightProvider:
    needs_audio_file = False

    def __init__(self, model: str = "claude-sonnet-4-6", timeout: int = 180, runner=None):
        self._model = model
        self._timeout = timeout
        self._runner = runner or _default_runner

    def analyze(self, ctx: dict) -> List[HighlightSegment]:
        transcript = ctx.get("transcript_segments") or []
        if not transcript:
            return []
        duration_ms = ctx.get("duration_ms") or 0
        clip_count = ctx.get("clip_count", 3)
        scenarios = ctx.get("target_scenarios") or ["feed"]
        content = ctx.get("content") or {}
        candidate_windows = ctx.get("candidate_windows") or []
        prompt = (
            _HL_SYSTEM + "\n\n"
            + _hl_build_user(content, transcript, scenarios, clip_count, duration_ms, candidate_windows)
            + _HL_INSTRUCTION
        )
        raw = _run_and_parse(self._runner, prompt, self._model, self._timeout)
        if not raw:
            _log.warning("ClaudeCliHighlightProvider: no parseable highlights from CLI")
        return _to_segments(raw.get("segments", []), transcript, duration_ms, scenarios, clip_count)


class ClaudeCliPackagingProvider:
    def __init__(self, model: str = "claude-sonnet-4-6", timeout: int = 120,
                 cover_max: int = 12, runner=None):
        self._model = model
        self._timeout = timeout
        self._cover_max = cover_max
        self._runner = runner or _default_runner

    def generate(self, ctx: dict) -> Packaging:
        prompt = _PK_SYSTEM + "\n\n" + _pk_build_user(ctx) + _PK_INSTRUCTION
        raw = _run_and_parse(self._runner, prompt, self._model, self._timeout)
        if not raw:
            _log.warning("ClaudeCliPackagingProvider: no parseable packaging from CLI (using fallback)")
        return _to_packaging(raw, ctx, self._cover_max)
