import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ['DATABASE_URL']

def get_db_connection():
    """Returns a new psycopg2 connection."""
    return psycopg2.connect(DATABASE_URL)

# ----------------------------------------------------------------------
# 1) Submit a new order  (now returns order_id)
# ----------------------------------------------------------------------
@app.route('/submit-order', methods=['POST'])
def submit_order():
    data   = request.json
    name   = data.get('name')
    phone  = data.get('phone')
    table  = data.get('table')
    items  = data.get('items', [])
    total  = float(data.get('total', 0))

    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (name, phone, table_number, item, total, status, created_at)
            VALUES (%s, %s, %s, %s, %s, DEFAULT, DEFAULT)
            RETURNING id;                                  -- 🆕
            """,
            (name, phone, table, json.dumps(items, ensure_ascii=False), total),
        )
        new_id = cur.fetchone()[0]                         # 🆕
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'message': 'Order received successfully!', 'order_id': new_id}), 200
    except Exception as e:
        print("Error in /submit-order:", e)
        return jsonify({'error': 'Failed to submit order'}), 500

# ----------------------------------------------------------------------
# 2) Get all active orders
# ----------------------------------------------------------------------
@app.route('/get-orders', methods=['GET'])
def get_orders():
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, phone, table_number, item, total
            FROM orders
            WHERE status != 'completed'
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall(); orders = []
        for row in rows:
            try:
                parsed_items = json.loads(row[4]) if isinstance(row[4], str) else row[4]
            except Exception as parse_error:
                print(f"❌ JSON decode error in row {row[0]}:", parse_error)
                parsed_items = []
            orders.append({
                'id'   : row[0],
                'name' : row[1],
                'phone': row[2],
                'table': row[3],
                'items': parsed_items,
                'total': float(row[5]),
            })
        cur.close(); conn.close()
        return jsonify(orders), 200
    except Exception as e:
        import traceback
        print("❌ Error in /get-orders:", e)
        traceback.print_exc()
        return jsonify({'error': 'Failed to retrieve orders'}), 500

# ----------------------------------------------------------------------
# 3) Mark a single order as completed
# ----------------------------------------------------------------------
@app.route('/delete-order/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute(
            "UPDATE orders SET status = 'completed' WHERE id = %s",
            (order_id,),
        )
        conn.commit(); cur.close(); conn.close()
        return jsonify({'message': 'Order marked as completed!'}), 200
    except Exception as e:
        print("Error in /delete-order:", e)
        return jsonify({'error': 'Failed to update order status'}), 500

# ----------------------------------------------------------------------
# 4) Mark ALL orders as completed
# ----------------------------------------------------------------------
@app.route('/delete-all-orders', methods=['DELETE'])
def delete_all_orders():
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE orders SET status = 'completed' WHERE status != 'completed'")
        conn.commit(); cur.close(); conn.close()
        return jsonify({'message': 'All orders marked as completed!'}), 200
    except Exception as e:
        print("Error in /delete-all-orders:", e)
        return jsonify({'error': 'Failed to update orders'}), 500

# ----------------------------------------------------------------------
# 5) Delete one item from an order and recalc total
# ----------------------------------------------------------------------
@app.route('/delete-item/<int:order_id>/<int:item_index>', methods=['POST'])
def delete_item(order_id, item_index):
    """Remove a single item; update total; if none left, mark completed."""
    try:
        conn = get_db_connection(); cur = conn.cursor()

        # Fetch existing items
        cur.execute("SELECT item FROM orders WHERE id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Order not found'}), 404

        items = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if item_index < 0 or item_index >= len(items):
            return jsonify({'error': 'Item index out of range'}), 400

        # Remove item
        items.pop(item_index)

        if items:
            new_total = sum(float(i.get('price', 0)) for i in items)
            cur.execute(
                "UPDATE orders SET item = %s, total = %s WHERE id = %s",
                (json.dumps(items, ensure_ascii=False), new_total, order_id),
            )
        else:
            # No items left: mark completed & zero out total
            cur.execute(
                "UPDATE orders SET status = 'completed', total = 0 WHERE id = %s",
                (order_id,),
            )

        conn.commit(); cur.close(); conn.close()
        return jsonify({'message': 'Item deleted and total updated!'}), 200

    except Exception as e:
        print("Error in /delete-item:", e)
        return jsonify({'error': 'Failed to delete item'}), 500


#-----------------------------------------------------------------------
# order tracking
#-----------------------------------------------------------------------
@app.route('/order-status', methods=['GET'])
def order_status():
    phone  = request.args.get('phone')
    order_id = request.args.get('order', type=int)  # optional

    if not phone:
      return jsonify({'found': False, 'error': 'phone_required'}), 400

    try:
        conn = get_db_connection(); cur = conn.cursor()
        if order_id:
            cur.execute("SELECT status FROM orders WHERE id=%s AND phone=%s",
                        (order_id, phone))
        else:
            # last order by phone
            cur.execute("""
              SELECT status FROM orders
              WHERE phone=%s ORDER BY id DESC LIMIT 1
            """, (phone,))
        row = cur.fetchone()
        cur.close(); conn.close()

        if row:
            return jsonify({'found': True, 'status': row[0]}), 200
        return jsonify({'found': False}), 404
    except Exception as e:
        print("error in /order-status:", e)
        return jsonify({'found': False, 'error': 'server'}), 500

# ----------------------------------------------------------------------
# Run locally
# ----------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)
