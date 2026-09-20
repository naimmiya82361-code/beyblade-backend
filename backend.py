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

app = Flask(__name__)
CORS(app)

# ============================================
# 🔧 CONFIG — YAHAN APNI DETAILS DAALO
# ============================================
FAMPAY_API_KEY = "fam_d7394c3e6dc5c9cdab27e426a744f85d9f9bdc9d"
FAMPAY_UPI_ID = "fathernajim@fam"
FAMPAY_BASE_URL = "https://famgateway.in/api"
FIREBASE_DB_URL = "https://bey-blade-5a65f-default-rtdb.firebaseio.com"
FIREBASE_CRED_PATH = "firebase-service-account.json"

# Initialize Firebase
cred = credentials.Certificate(FIREBASE_CRED_PATH)
firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})


# ============================================
# CREATE ORDER
# ============================================
@app.route('/api/fam/create-order', methods=['POST'])
def create_order():
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
                "redirect_url": "https://rambhaipanel.shop/success"
            },
            timeout=15
        )

        result = resp.json()

        if result.get("status") != "success":
            return jsonify({
                "success": False,
                "message": result.get("message", "API Error")
            }), 400

        order_data = result.get("data", {})
        order_id = order_data.get("order_id")

        if order_id:
            db.reference(f'pending_orders/{order_id}').set({
                'order_id': order_id,
                'amount': float(amount),
                'user_id': user_id,
                'status': 'pending'
            })

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
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================
# VERIFY PAYMENT
# ============================================
@app.route('/api/fam/verify', methods=['POST'])
def verify_payment():
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
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================
# WEBHOOK (optional)
# ============================================
@app.route('/api/fam/webhook', methods=['POST'])
def fam_webhook():
    data = request.json
    order_id = data.get('order_id')
    utr = data.get('utr')
    amount = data.get('amount')
    status = data.get('status')

    if status == 'success' and order_id:
        db.reference(f'pending_orders/{order_id}').update({
            'status': 'completed',
            'utr': utr,
            'amount': amount
        })

    return jsonify({"success": True}), 200


# ============================================
# RUN
# ============================================
if __name__ == '__main__':
    print("🚀 FamPay Backend running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)