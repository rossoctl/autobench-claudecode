"""Build a sanitized environment for a `claude -p` child.

Why this exists: the spike is being driven from inside an interactive Claude Code
session, whose environment carries CLAUDECODE=1, a messaging socket/token, a session
id and an exec path. A child inheriting those is a *nested* Claude Code, not the
plain-terminal invocation the harness will actually make. So strip that whole family
and keep only what a fresh login shell would have.

Auth on this machine is env/settings-based (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN
pointing at the internal ETE LiteLLM gateway) rather than OAuth/keychain, so those two
are passed through deliberately -- that is what lets a curated HOME still authenticate.
"""
import os

# Everything Claude Code injects to describe *this* session. A child must not see it.
_STRIP_EXACT = {
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
}
# Auth/routing we intentionally keep, so a curated HOME does not lose credentials.
_KEEP_ANTHROPIC = {"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"}


def child_env(extra=None, home=None, inherit_proxy=False):
    """A clean env for a headless `claude -p`.

    extra:         dict merged last (e.g. HTTPS_PROXY / NODE_EXTRA_CA_CERTS).
    home:          override HOME (assumption 3).
    inherit_proxy: keep any proxy vars already in this process (default: drop them, so
                   a test only sees the proxy when it explicitly asks for one).
    """
    env = {}
    for k, v in os.environ.items():
        if k in _STRIP_EXACT:
            continue
        if k.startswith("CLAUDE_CODE_"):
            continue
        if not inherit_proxy and k.upper() in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
        ):
            continue
        env[k] = v
    # CLAUDE_MODEL/ANTHROPIC_MODEL are ordinary config, not session identity: keep them
    # so the child uses the same model the harness would use.
    for k in _KEEP_ANTHROPIC:
        if k in os.environ:
            env[k] = os.environ[k]
    if home:
        env["HOME"] = home
    if extra:
        env.update(extra)
    return env


def summarize_env(env, keys):
    """Non-secret one-liner for the log: presence + length only for secrets."""
    out = []
    for k in keys:
        v = env.get(k)
        if v is None:
            out.append(f"{k}=<unset>")
        elif any(s in k.upper() for s in ("TOKEN", "KEY", "SECRET")):
            out.append(f"{k}=<set len={len(v)}>")
        else:
            out.append(f"{k}={v}")
    return "  ".join(out)
