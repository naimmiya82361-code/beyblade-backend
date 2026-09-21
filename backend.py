@app.route('/api/fam/webhook', methods=['POST', 'OPTIONS'])
def fam_webhook():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.json
    print(f"📩 Webhook received: {data}")
    
    order_id = data.get('order_id')
    utr = data.get('utr')
    amount = data.get('amount')
    status = data.get('status')

    if status == 'success' and order_id and firebase_initialized:
        try:
            order_ref = db.reference(f'pending_orders/{order_id}')
            order = order_ref.get()
            
            if not order:
                print(f"⚠️ Order not found: {order_id}")
                return jsonify({"success": False, "message": "Order not found"}), 404
            
            user_id = order.get('user_id')
            if not user_id:
                print(f"⚠️ User ID not found: {order_id}")
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
                    'order_id': order_id
                })
                
                order_ref.update({
                    'status': 'completed',
                    'utr': utr,
                    'amount': float(amount),
                    'completed_at': {'.sv': 'timestamp'}
                })
                
                print(f"✅ Balance added: {user_id} +₹{amount}")
            
            return jsonify({"success": True}), 200
            
        except Exception as e:
            print(f"❌ Webhook error: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    return jsonify({"success": True}), 200
