from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

import stripe
import os
import requests

from datetime import datetime, timedelta
from app.firebase import db

router = APIRouter()

# ================= ENV =================

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

FORTE_API_URL = os.getenv("FORTE_API_URL")
FORTE_USERNAME = os.getenv("FORTE_USERNAME")
FORTE_PASSWORD = os.getenv("FORTE_PASSWORD")

stripe.api_key = STRIPE_SECRET_KEY


# ================= STRIPE CHECKOUT =================

@router.get("/create-checkout-session")
async def create_checkout_session(request: Request):

    email = request.query_params.get("email")
    uid = request.query_params.get("uid")

    session = stripe.checkout.Session.create(
        client_reference_id=uid,
        payment_method_types=["card"],
        mode="payment",
        customer_email=email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Zodiac Wisdom"},
                "unit_amount": 999,
            },
            "quantity": 1,
        }],
        success_url="https://seid-chat.carrd.co",
        cancel_url="https://seidkona.carrd.co/",
    )

    return RedirectResponse(session.url)


# ================= STRIPE WEBHOOK =================

@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]
        uid = session.get("client_reference_id")

        if not uid:
            return {"status": "no user id"}

        user_ref = db.collection("users").document(uid)

        expires_at = datetime.utcnow() + timedelta(minutes=10)

        user_ref.set({
            "hasAccess": True,
            "expiresAt": expires_at
        }, merge=True)

        return {"status": "success"}

    return {"status": "ignored"}


# ================= FORTE CREATE ORDER =================

@router.get("/create-forte-order")
async def create_forte_order(uid: str, plan: str, lang: str = "ru"):

    if not FORTE_API_URL or not FORTE_USERNAME or not FORTE_PASSWORD:
        raise HTTPException(status_code=500, detail="Forte credentials not configured")

    plan = plan.strip().lower()
    lang = lang.strip().lower()

    if lang not in ["ru", "en"]:
        lang = "ru"

    # ===== тарифы =====

    if plan == "hour":
        amount = "9900.00"
    elif plan == "day":
        amount = "29990.00"
    elif plan == "month":
        amount = "89990.00"
    else:
        raise HTTPException(status_code=400, detail="Invalid plan")

    payload = {
        "order": {
            "typeRid": "Order_RID",
            "language": lang,
            "amount": amount,
            "currency": "KZT",
            "description": f"{uid}|{plan}|{lang}",
            "title": "Subscription",
            "hppRedirectUrl": "https://ei-brain.onrender.com/forte-success"
        }
    }

    response = requests.post(
        f"{FORTE_API_URL}/order",
        json=payload,
        auth=(FORTE_USERNAME, FORTE_PASSWORD),
        headers={"Content-Type": "application/json"}
    )

    response.raise_for_status()

    forte_response = response.json()

    order_id = str(forte_response["order"]["id"])
    order_password = forte_response["order"]["password"]
    hpp_url = forte_response["order"]["hppUrl"]

    db.collection("forte_orders").document(order_id).set({
        "uid": uid,
        "plan": plan,
        "lang": lang,
        "createdAt": datetime.utcnow(),
        "isProcessed": False
    })

    pay_url = f"{hpp_url}?id={order_id}&password={order_password}"

    return RedirectResponse(pay_url)


# ================= FORTE VERIFY AFTER PAYMENT =================

@router.get("/forte-success")
async def forte_success(request: Request):

    try:

        order_id = request.query_params.get("ID") or request.query_params.get("id")

        if not order_id:
            return {"error": "No order id received from Forte"}

        response = requests.get(
            f"{FORTE_API_URL}/order/{order_id}",
            auth=(FORTE_USERNAME, FORTE_PASSWORD)
        )

        result = response.json()
        order_status = result.get("order", {}).get("status")

        if order_status not in ["FullyPaid", "Approved", "Deposited"]:
            return RedirectResponse("https://gna-ei.kz/payment-failed")

        order_doc = db.collection("forte_orders").document(order_id).get()

        if not order_doc.exists:
            return RedirectResponse("https://gna-ei.kz/payment-failed")

        order_info = order_doc.to_dict()

        if order_info.get("isProcessed"):
            if order_info.get("lang") == "en":
                return RedirectResponse("https://gna-ei.kz/nj-assistant-en")

            return RedirectResponse("https://gna-ei.kz/nj-assistant")

        uid = order_info["uid"]
        plan = order_info["plan"]
        lang = order_info["lang"]

        now = datetime.utcnow()

        if plan == "hour":
            duration = timedelta(hours=1)

        elif plan == "day":
            duration = timedelta(days=1)

        elif plan == "month":
            duration = timedelta(days=30)

        else:
            return {"error": "Invalid plan"}

        expires_at = (now + duration).replace(microsecond=0)

        db.collection("users").document(uid).set({
            "hasAccess": True,
            "isPaid": True,
            "planType": plan,
            "expiresAt": expires_at,
            "expiresAtFormatted": expires_at.strftime("%d.%m.%Y %H:%M:%S"),
            "lastPaymentAt": now
        }, merge=True)

        db.collection("forte_orders").document(order_id).update({
            "isProcessed": True,
            "paidAt": now
        })

        db.collection("payments").document(order_id).set({
            "uid": uid,
            "plan": plan,
            "status": order_status,
            "orderId": order_id,
            "createdAt": now
        })

        if lang == "en":
            return RedirectResponse("https://gna-ei.kz/online-session-en")

        return RedirectResponse("https://gna-ei.kz/online-session")

    except Exception as e:
        return {"error": str(e)}
