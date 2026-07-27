"""Outbound notifications. Currently a single Discord webhook used to announce
when a contributor schedules a record for transcription. Best-effort: a failed
or unconfigured webhook never breaks the request that triggered it."""

from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger("notify")


def transcribe_scheduled(occ_id: str, user_id: int) -> bool:
    """Post a 'scheduled for transcription' message to Discord. Returns True if a
    webhook is configured and the post succeeded, else False (caller ignores it).

    Identifies the requester by our internal user id, not by name or ORCID iD:
    Discord is outside the platform's trust boundary, so the message carries only
    opaque keys that need DB access to resolve to a person."""
    url = settings.discord_webhook_url.strip()
    if not url:
        return False

    content = f"🗒️ **Scheduled for transcription** by user `{user_id}`\nRecord `{occ_id}`"
    try:
        resp = httpx.post(url, json={"content": content}, timeout=5.0)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("Discord transcribe-schedule notification failed: %s", e)
        return False
