"""Server-side AI endpoints."""
from __future__ import annotations

import json
import os
from urllib import error, request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from models.user import User
from services.auth import get_current_user

router = APIRouter()


class AIAnalyzeRequest(BaseModel):
    """Prompt payload for server-side AI analysis."""

    prompt: str = Field(min_length=1)
    model: str = Field(default="gemini-2.5-flash")


class AIAnalyzeResponse(BaseModel):
    """Normalized AI response."""

    text: str


def _call_gemini(prompt: str, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 600,
            },
        }
    ).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {detail or exc.reason}") from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {exc.reason}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise HTTPException(status_code=502, detail="Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
    if not text:
        raise HTTPException(status_code=502, detail="Gemini returned an empty response")
    return text


@router.post("/analyze", response_model=AIAnalyzeResponse)
async def analyze_with_ai(
    payload: AIAnalyzeRequest,
    user: User = Depends(get_current_user),
):
    """Analyze business context using the configured AI provider."""
    _ = user
    return AIAnalyzeResponse(text=_call_gemini(payload.prompt, payload.model))
