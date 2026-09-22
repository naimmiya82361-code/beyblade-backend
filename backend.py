"""
FamAPI Auto-Verify Backend
===========================
Requirements:
    pip install flask flask-cors requests firebase-admin
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import firebase_admin
from firebase_admin import credentials, db
import os
import json
import traceback

app = Flask(__name__)

# ============================================
# ✅ CORS FIX
# ============================================
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


# ============================================
# 🔧 CONFIG — FamAPI
# ============================================
FAMPAY_API_KEY = os.environ.get("FAMPAY_API_KEY", "FAM_LIVE_sk_KGKthfsQ8hsCuzX8XRYrb1cKXkJZwh6f")
FAMPAY_BASE_URL = "https://py.freepanel.in/api/v1"
FIREBASE_DB_URL = "https://bey-blade-5a65f-default-rtdb.firebaseio.com"


# ============================================
# ✅ Firebase Init
# ============================================
firebase_initialized = False

if os.path.exists("firebase-service-account.json"):
    try:
        cred = credentials.Certificate("firebase-service-account.json")
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
        firebase_initialized = True
        print("✅ Firebase initialized from JSON file")
    except Exception as e:
        print(f"❌ Firebase file error: {e}")
        traceback.print_exc()

if not firebase_initialized:
    firebase_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if firebase_json:
        try:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
            firebase_initialized = True
            print("✅ Firebase initialized from env variable")
        except Exception as e:
            print(f"❌ Firebase env error: {e}")
            traceback.print_exc()

if not firebase_initialized:
    print("⚠️ Firebase NOT initialized")


# ============================================
# ✅ HEALTH CHECK
# ============================================
@app.route('/healthz')
def healthz():
    return jsonify({
        "status": "ok",
        "firebase": firebase_initialized
    }), 200


# ============================================
# ✅ ROOT
# ============================================
@app.route('/')
def root():
    return jsonify({
        "status": "ok",
        "service": "BEYBLADE FamAPI Backend",
        "firebase": firebase_initialized,
        "endpoints": [
            "/healthz",
            "/api/fam/create-order",
            "/api/fam/verify",
            "/api/fam/webhook"
        ]
    }), 200


# ============================================
# ✅ CREATE ORDER (FamAPI)
# ============================================
@app.route('/api/fam/create-order', methods=['POST', 'OPTIONS'])
def create_order():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.json
    amount = data.get('amount')
    user_id = data.get('user_id')
    mobile = data.get('mobile', '')

    if not amount or float(amount) < 1:
        return jsonify({"success": False, "message": "Invalid amount"}), 400

    try:
        # FamAPI me amount PAISE me jaata hai (₹1 = 100 paise)
        amount_paise = int(float(amount) * 100)
        
        resp = requests.post(
            f"{FAMPAY_BASE_URL}/orders",
            headers={
                "Authorization": f"Bearer {FAMPAY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "amount": amount_paise,
                "receipt": f"BEY_{user_id}_{int(float(amount))}",
                "redirect_url": "https://beyblade-store.netlify.app/success"
            },
            timeout=15
        )

        result = resp.json()
        print(f"📦 Create order response: {result}")

        # FamAPI response check
        if not result.get("success") and result.get("status") != "success":
            return jsonify({
                "success": False,
                "message": result.get("message", result.get("error", "API Error"))
            }), 400

        order_data = result.get("data", result)
        order_id = order_data.get("order_id") or order_data.get("id")

        if order_id and firebase_initialized:
            try:
                db.reference(f'pending_orders/{order_id}').set({
                    'order_id': order_id,
                    'amount': float(amount),
                    'user_id': user_id,
                    'status': 'pending'
                })
            except Exception as e:
                print(f"Firebase save error: {e}")

        return jsonify({
            "success": True,
            "order_id": order_id,
            "qr_code": order_data.get("qr_code") or order_data.get("qr_url"),
            "upi_string": order_data.get("upi_string") or order_data.get("upi_intent"),
            "checkout_url": order_data.get("payment_url") or order_data.get("checkout_url"),
            "amount": amount
        })

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "message": "API timeout"}), 504
    except Exception as e:
        print(f"❌ Create order error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================
# ✅ VERIFY PAYMENT (FamAPI)
# ============================================
@app.route('/api/fam/verify', methods=['POST', 'OPTIONS'])
def verify_payment():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.json
    order_id = data.get('order_id')

    if not order_id:
        return jsonify({"success": False, "message": "Order ID required"}), 400

    try:
        resp = requests.get(
            f"{FAMPAY_BASE_URL}/orders/{order_id}",
            headers={"Authorization": f"Bearer {FAMPAY_API_KEY}"},
            timeout=15
        )
        result = resp.json()
        print(f"🔍 Verify response: {result}")

        order_data = result.get("data", result)
        status = order_data.get("status", "").lower()

        if status in ["success", "completed", "paid"]:
            return jsonify({
                "success": True,
                "verified": True,
                "utr": order_data.get("utr", ""),
                "amount": order_data.get("amount", 0) / 100,
                "order_id": order_id
            })
        else:
            return jsonify({
                "success": False,
                "verified": False,
                "message": result.get("message", "Payment not verified")
            })

    except Exception as e:
        print(f"❌ Verify error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================
# ✅ WEBHOOK (FamAPI)
# ============================================
@app.route('/api/fam/webhook', methods=['POST', 'OPTIONS', 'GET', 'HEAD'])
def fam_webhook():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    if request.method == 'GET' or request.method == 'HEAD':
        return jsonify({
            "status": "ok",
            "message": "Webhook endpoint active",
            "firebase": firebase_initialized
        }), 200

    try:
        data = request.json
        print(f"📩 Webhook received: {data}")
        
        # FamAPI webhook fields (flexible)
        order_id = data.get('order_id') or data.get('id')
        amount = data.get('amount')
        status = (data.get('status') or data.get('event') or '').lower()
        utr = data.get('utr') or data.get('transaction_id')
        
        # Amount paise me aata hai — rupees me convert
        if amount:
            try:
                amount = float(amount) / 100 if float(amount) > 100 else float(amount)
            except:
                pass

        if status in ['success', 'completed', 'paid', 'payment.success'] and firebase_initialized:
            try:
                # Order id se dhundho
                order_ref = db.reference(f'pending_orders/{order_id}')
                order = order_ref.get()
                
                # Agar direct order nahi mila to amount se match karo
                if not order:
                    orders_ref = db.reference('pending_orders')
                    all_orders = orders_ref.get() or {}
                    for oid, o in all_orders.items():
                        if o.get('status') == 'pending':
                            if abs(float(o.get('amount', 0)) - float(amount)) < 0.01:
                                order = o
                                order_id = oid
                                break
                
                if not order:
                    print(f"⚠️ Order not found: {order_id}")
                    return jsonify({"success": True, "message": "Order not found"}), 200
                
                user_id = order.get('user_id')
                if not user_id:
                    print(f"⚠️ User not found in order: {order_id}")
                    return jsonify({"success": True}), 200
                
                user_ref = db.reference(f'users/{user_id}')
                user = user_ref.get()
                
                if user:
                    old_balance = float(user.get('balance', 0))
                    new_balance = old_balance + float(amount)
                    
                    user_ref.update({'balance': new_balance})
                    
                    db.reference(f'users/{user_id}/transactions').push({
                        'type': 'Deposit',
                        'amount': float(amount),
                        'description': f'FamAPI Auto-Verified - UTR: {utr}',
                        'date': {'.sv': 'timestamp'},
                        'gateway': 'FamAPI',
                        'utr': utr,
                        'order_id': order_id
                    })
                    
                    db.reference(f'pending_orders/{order_id}').update({
                        'status': 'completed',
                        'utr': utr,
                        'amount': float(amount),
                        'completed_at': {'.sv': 'timestamp'}
                    })
                    
                    print(f"✅ Balance added: {user_id} +₹{amount}")
                
                return jsonify({"success": True}), 200
                
            except Exception as e:
                print(f"❌ Webhook processing error: {e}")
                traceback.print_exc()
                return jsonify({"success": False, "message": str(e)}), 500

        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================
# ✅ RUN
# ============================================
if __name__ == '__main__':
    print("🚀 FamAPI Backend running")
    print(f"Firebase: {'✅ Connected' if firebase_initialized else '❌ NOT Connected'}")
    app.run(host='0.0.0.0', port=5000, debug=False)
