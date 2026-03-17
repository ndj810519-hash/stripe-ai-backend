from fastapi import APIRouter
from datetime import datetime
from app.firebase import db

router = APIRouter()


@router.get("/check-access")
async def check_access(uid: str):

    user_ref = db.collection("users").document(uid)
    user = user_ref.get()

    if not user.exists:
        return {"access": False}

    data = user.to_dict()

    if not data.get("hasAccess"):
        return {"access": False}

    expires_at = data.get("expiresAt")

    if datetime.utcnow() > expires_at:

        user_ref.update({
            "hasAccess": False,
            "minutesRemaining": 0
        })

        return {"access": False}

    return {"access": True}


@router.get("/subscription-status")
def subscription_status(uid: str):

    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return {"hasAccess": False, "remainingSeconds": 0}

    user_data = user_doc.to_dict()
    expires_at = user_data.get("expiresAt")

    if not expires_at:
        return {"hasAccess": False, "remainingSeconds": 0}

    if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=None)

    now = datetime.utcnow()
    remaining_seconds = int((expires_at - now).total_seconds())

    if remaining_seconds <= 0:
        return {"hasAccess": False, "remainingSeconds": 0}

    return {
        "hasAccess": True,
        "remainingSeconds": remaining_seconds,
        "expiresAt": expires_at
    }
