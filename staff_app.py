import os, json
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from dotenv import load_dotenv

# Load .env explicitly from the backend folder
env_path = os.path.join(os.path.dirname(__file__), ".env")
print("DEBUG: loading", env_path, "exists?", os.path.exists(env_path))
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")
print("DEBUG: DATABASE_URL =", DATABASE_URL)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Put it in backend/.env or export it in your shell.")



# ------------- DB helpers -------------
def get_db():
    if 'db' not in g:
        # Railway requires sslmode=require (already in your URL)
        g.db = psycopg2.connect(DATABASE_URL)
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
              id SERIAL PRIMARY KEY,
              name TEXT,
              phone TEXT,
              table_number TEXT,
              item JSONB,
              total DOUBLE PRECISION,
              status TEXT DEFAULT 'pending',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

# ------------- Routes -------------
@app.route('/', methods=['GET'])
def root():
    import os
    return {'ok': True, 'db_host': os.getenv("DATABASE_URL").split('@')[1].split('/')[0]}

@app.route('/favicon.ico')
def favicon():
    return ('', 204)

@app.route('/submit-order', methods=['POST'])
def submit_order():
    data = request.json or {}

    # build safe, explicit values
    items = data.get('items') or []
    try:
        total = float(data.get('total') or 0)
    except Exception:
        total = 0.0

    sql = """
        INSERT INTO orders (name, phone, table_number, item, total, status)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    values = (
        (data.get('name') or '').strip(),
        (data.get('phone') or '').strip(),
        (data.get('table') or '').strip(),
        json.dumps(items, ensure_ascii=False),
        total,
        'pending',
    )

    conn = get_db()
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Debug if needed:
        # print("DEBUG values:", values, type(values))
        cur.execute(sql, values)
        new_id = cur.fetchone()['id']

    return jsonify({'message': 'Order received successfully!', 'order_id': new_id}), 200



@app.route('/get-orders', methods=['GET'])
def get_orders():
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, phone, table_number, item, total
            FROM orders
            WHERE status != 'completed'
            ORDER BY id ASC
        """)
        rows = cur.fetchall()

    orders = []
    for row in rows:
        items = row['item'] or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        orders.append({
            'id': row['id'],
            'name': row['name'],
            'phone': row['phone'],
            'table': row['table_number'],
            'items': items,
            'total': float(row['total'] or 0),
        })
    return jsonify(orders), 200


@app.route('/delete-order/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = 'completed' WHERE id = %s", (order_id,))
    return jsonify({'message': 'Order marked as completed!'}), 200


@app.route('/delete-all-orders', methods=['DELETE'])
def delete_all_orders():
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = 'completed' WHERE status != 'completed'")
    return jsonify({'message': 'All orders marked as completed!'}), 200


@app.route('/delete-item/<int:order_id>/<int:item_index>', methods=['POST'])
def delete_item(order_id, item_index):
    conn = get_db()
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT item FROM orders WHERE id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'Order not found'}), 404

        items = row['item'] or []
        if isinstance(items, str):
            items = json.loads(items)

        if not (0 <= item_index < len(items)):
            return jsonify({'error': 'Item index out of range'}), 400

        items.pop(item_index)
        if items:
            new_total = sum(float(i.get('price', 0)) for i in items)
            cur.execute(
                "UPDATE orders SET item = %s, total = %s WHERE id = %s",
                (json.dumps(items, ensure_ascii=False), new_total, order_id)
            )
        else:
            # no items left — mark completed
            cur.execute(
                "UPDATE orders SET status = 'completed', total = 0, item = '[]'::jsonb WHERE id = %s",
                (order_id,)
            )
    return jsonify({'message': 'Item deleted and total updated!'}), 200


@app.route('/order-status', methods=['GET'])
def order_status():
    phone = request.args.get('phone')
    if not phone:
        return jsonify({'found': False, 'error': 'phone_required'}), 400
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM orders WHERE phone = %s ORDER BY id DESC LIMIT 1",
            (phone,)
        )
        row = cur.fetchone()
    if row:
        return jsonify({'found': True, 'status': row[0]}), 200
    return jsonify({'found': False}), 404

# at bottom of backend/staff_app.py
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))  # make sure we load backend/.env

    with app.app_context():       # <-- IMPORTANT
        init_db()

    print("DB URL set?", bool(os.getenv("DATABASE_URL")))
    app.run(debug=True, host='0.0.0.0', port=5000)

