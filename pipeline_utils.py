"""Shared pipeline utilities for API usage logging."""

import os
import logging
import threading

import requests

log = logging.getLogger(__name__)


def log_api_usage(
    *,
    source: str,          # 'pipeline' or 'external'
    category: str,        # 'llm', 'search_api', 'dataset_api'
    operation: str,       # e.g. 'job_eval', 'serpapi_search'
    provider: str = None,
    model: str = None,
    prompt_tokens: int = None,
    completion_tokens: int = None,
    total_tokens: int = None,
    cost_usd: float = None,
    latency_ms: int = None,
    user_id: str = None,
    http_status: int = None,
    success: bool = True,
    metadata: dict = None,
    config: dict = None,
):
    """Fire-and-forget insert to Supabase api_usage_log. Never raises."""
    def _post():
        try:
            supabase_url = os.environ.get("SUPABASE_URL") or (config or {}).get("supabase_url", "")
            supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or (config or {}).get("supabase_service_role_key", "")
            if not supabase_url or not supabase_key:
                return

            row = {
                "source": source,
                "category": category,
                "operation": operation,
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "user_id": user_id,
                "http_status": http_status,
                "success": success,
                "metadata": metadata,
            }
            # Remove None values
            row = {k: v for k, v in row.items() if v is not None}

            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            }
            requests.post(
                f"{supabase_url}/rest/v1/api_usage_log",
                headers=headers,
                json=row,
                timeout=10,
            )
        except Exception:
            pass  # never block the pipeline

    threading.Thread(target=_post, daemon=True).start()
