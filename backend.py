"""
FamPay Auto-Verify Backend
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
# 🔧 CONFIG
# ============================================
FAMPAY_API_KEY = os.environ.get("FAMPAY_API_KEY", "fam_d7394c3e6dc5c9cdab27e426a744f85d9f9bdc9d")
FAMPAY_UPI_ID = "fathernajim@fam"
FAMPAY_BASE_URL = "https://famgateway.in/api"
FIREBASE_DB_URL = "https://bey-blade-5a65f-default-rtdb.firebaseio.com"


# ============================================
# ✅ Firebase Init
# ============================================
firebase_initialized = False

# Tarika 1: JSON file se
if os.path.exists("firebase-service-account.json"):
    try:
        cred = credentials.Certificate("firebase-service-account.json")
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
        firebase_initialized = True
        print("✅ Firebase initialized from JSON file")
    except Exception as e:
        print(f"❌ Firebase file error: {e}")
        traceback.print_exc()

# Tarika 2: Environment variable se
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
# ✅ CREATE ORDER
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
        resp = requests.post(
            f"{FAMPAY_BASE_URL}/create-order.php",
            headers={
                "Authorization": f"Bearer {FAMPAY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "amount": float(amount),
                "redirect_url": "https://beyblade-store.netlify.app/success"
            },
            timeout=15
        )

        result = resp.json()
        print(f"📦 Create order response: {result}")

        if result.get("status") != "success":
            return jsonify({
                "success": False,
                "message": result.get("message", "API Error")
            }), 400

        order_data = result.get("data", {})
        order_id = order_data.get("order_id")

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
            "qr_code": order_data.get("qr_url"),
            "upi_string": order_data.get("upi_intent"),
            "checkout_url": order_data.get("checkout_url"),
            "amount": amount
        })

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "message": "API timeout"}), 504
    except Exception as e:
        print(f"❌ Create order error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================
# ✅ VERIFY PAYMENT
# ============================================
@app.route('/api/fam/verify', methods=['POST', 'OPTIONS'])
def verify_payment():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.json
    order_id = data.get('order_id')
    amount = data.get('amount')
    utr = data.get('utr', '').strip()

    if not order_id:
        return jsonify({"success": False, "message": "Order ID required"}), 400

    try:
        resp = requests.get(
            f"{FAMPAY_BASE_URL}/verify-order.php",
            headers={"Authorization": f"Bearer {FAMPAY_API_KEY}"},
            params={"order_id": order_id},
            timeout=15
        )
        result = resp.json()
        print(f"🔍 Verify response: {result}")

        if result.get("status") == "success" or result.get("verified") == True:
            return jsonify({
                "success": True,
                "verified": True,
                "utr": result.get("data", {}).get("utr", utr),
                "amount": result.get("data", {}).get("amount", amount),
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
# ✅ WEBHOOK
# ============================================
@app.route('/api/fam/webhook', methods=['POST', 'OPTIONS'])
def fam_webhook():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    try:
        data = request.json
        print(f"📩 Webhook received: {data}")
        
        utr = data.get('utr')
        amount = data.get('amount')
        status = data.get('status')
        transaction_id = data.get('transaction_id')

        if status == 'success' and firebase_initialized:
            try:
                orders_ref = db.reference('pending_orders')
                all_orders = orders_ref.get() or {}
                
                matched_order_id = None
                matched_order = None
                
                for oid, order in all_orders.items():
                    if order.get('status') == 'pending':
                        order_amount = float(order.get('amount', 0))
                        if abs(order_amount - float(amount)) < 0.01:
                            matched_order_id = oid
                            matched_order = order
                            break
                
                if not matched_order_id:
                    print(f"⚠️ No pending order found for ₹{amount}")
                    return jsonify({"success": False, "message": "Order not found"}), 404
                
                user_id = matched_order.get('user_id')
                if not user_id:
                    print(f"⚠️ User ID not found in order: {matched_order_id}")
                    return jsonify({"success": False, "message": "User not found"}), 404
                
                user_ref = db.reference(f'users/{user_id}')
                user = user_ref.get()
                
                if user:
                    old_balance = float(user.get('balance', 0))
                    new_balance = old_balance + float(amount)
                    
                    user_ref.update({'balance': new_balance})
                    
                    db.reference(f'users/{user_id}/transactions').push({
                        'type': 'Deposit',
                        'amount': float(amount),
                        'description': f'FamPay Auto-Verified - UTR: {utr}',
                        'date': {'.sv': 'timestamp'},
                        'gateway': 'FamPay',
                        'utr': utr,
                        'transaction_id': transaction_id
                    })
                    
                    db.reference(f'pending_orders/{matched_order_id}').update({
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
    print("🚀 FamPay Backend running")
    app.run(host='0.0.0.0', port=5000, debug=False)
