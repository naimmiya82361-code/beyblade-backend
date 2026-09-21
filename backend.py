# ============================================
# ✅ WEBHOOK
# ============================================
@app.route('/api/fam/webhook', methods=['POST', 'OPTIONS'])
def fam_webhook():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.json
    print(f"📩 Webhook received: {data}")
    
    utr = data.get('utr')
    amount = data.get('amount')
    status = data.get('status')
    transaction_id = data.get('transaction_id')

    if status == 'success' and firebase_initialized:
        try:
            # UTR se pending order dhundho
            orders_ref = db.reference('pending_orders')
            all_orders = orders_ref.get() or {}
            
            matched_order_id = None
            matched_order = None
            
            # Har order check karo — amount match karo
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
                
                # Order complete mark karo
                db.reference(f'pending_orders/{matched_order_id}').update({
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