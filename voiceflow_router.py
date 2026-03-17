from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import uuid
import requests

from datetime import datetime
from app.firebase import db

router = APIRouter()

VOICEFLOW_API_KEY = os.getenv("VOICEFLOW_API_KEY")
VOICEFLOW_PROJECT_ID = os.getenv("VOICEFLOW_PROJECT_ID")


class UserMessage(BaseModel):
    message: str
    user_id: str | None = None


@router.post("/ask")
def ask_voiceflow(data: UserMessage):

    user_id = data.user_id or str(uuid.uuid4())

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=403, detail="User not found")

    user_data = user_doc.to_dict()
    expires_at = user_data.get("expiresAt")

    if not expires_at:
        raise HTTPException(status_code=403, detail="No active subscription")

    if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=None)

    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Subscription expired")

    url = f"https://general-runtime.voiceflow.com/state/user/{user_id}/interact"

    headers = {
        "Authorization": VOICEFLOW_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "request": {
            "type": "text",
            "payload": data.message
        },
        "config": {
            "tts": False,
            "stripSSML": True
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        params={"projectID": VOICEFLOW_PROJECT_ID}
    )

    traces = response.json()

    texts = []
    for trace in traces:
        if trace.get("type") == "text":
            texts.append(trace["payload"]["message"])

    return {"text": "\n".join(texts)}
