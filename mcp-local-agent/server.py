#!/usr/bin/env python3
"""
Local-model delegation MCP server for Signal Forge.

Exposes one tool, delegate_to_local_model, backed by a local Ollama model
(qwen2.5:7b by default -- already pulled, ~4.7GB, chosen over qwen2.5:14b to
leave RAM headroom on a 16GB machine, and over pulling an actual Llama model
since nothing here depends on the Llama family specifically).

Scope, by design (per the "scoped delegation" choice, not "full handover"):
this tool is for bounded, mechanical subtasks only -- bulk find/replace text
generation, repetitive data entry, grinding through a checklist of similar
edits. It has NO file or shell access of its own; it only returns text. The
calling agent (Claude) stays responsible for diagnosis, design decisions,
applying any edits, and verification. Do not use this for anything where a
wrong answer would be expensive to catch late.
"""
import json
import urllib.request
import urllib.error

from mcp.server.fastmcp import FastMCP

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"

mcp = FastMCP("signalforge-local-agent")


@mcp.tool()
def delegate_to_local_model(task: str, context: str = "") -> str:
    """Delegate a bounded, mechanical subtask to the local qwen2.5:7b model.

    Use this for repetitive, well-specified work where a wrong answer is
    cheap to spot and fix -- e.g. "generate N similar lines following this
    exact pattern", "reformat this data", "draft filler text for a
    placeholder". Do NOT use it for diagnosis, design decisions, or anything
    that needs careful verification -- keep that with the calling agent.

    Args:
        task: The specific, bounded instruction to carry out.
        context: Any surrounding data/examples the model needs (card lists,
            a pattern to follow, existing text to transform).

    Returns:
        The local model's raw text response, or a clear error string if
        Ollama isn't reachable.
    """
    prompt = task if not context else f"{task}\n\n---\nContext:\n{context}"
    payload = json.dumps({"model": MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()
    except urllib.error.URLError as e:
        return (
            f"ERROR: could not reach Ollama at {OLLAMA_URL} ({e}). "
            "Local Ollama server is likely not running -- start it with "
            "`ollama serve` (or `nohup ollama serve &` to background it), "
            "then retry."
        )


if __name__ == "__main__":
    mcp.run()
