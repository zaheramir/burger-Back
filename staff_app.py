# staff_app.py
import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from dotenv import load_dotenv

load_dotenv()  # harmless on Railway; useful locally

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

def _jsonify_items(raw):
    """raw may be JSONB (already a Python obj) or a JSON/text string."""
    if raw is None:
        return []
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []

def _conn():
    """New connection per request; sets search_path to public."""
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO public;")
    return conn

@app.route("/", methods=["GET"])
def health():
    return {"ok": True}

# ---------------- Submit order ----------------
@app.route("/submit-order", methods=["POST"])
def submit_order():
    data  = request.get_json(force=True, silent=True) or {}
    name  = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    table = (data.get("table") or "").strip()
    items = data.get("items") or []
    total = float(data.get("total") or 0)

    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (name, phone, table_number, item, total, status, created_at)
                VALUES (%s, %s, %s, %s, %s, DEFAULT, DEFAULT)
                RETURNING id;
                """,
                (name, phone, table, json.dumps(items, ensure_ascii=False), total),
            )
            order_id = cur.fetchone()[0]
        return jsonify({"message": "Order received successfully!", "order_id": order_id}), 200
    except Exception as e:
        app.logger.exception("Error in /submit-order")
        return jsonify({"error": "Failed to submit order"}), 500

# ---------------- Get active orders ----------------
@app.route("/get-orders", methods=["GET"])
def get_orders():
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, phone, table_number, item, total
                FROM orders
                WHERE status IS DISTINCT FROM 'completed'
                ORDER BY id ASC;
                """
            )
            rows = cur.fetchall()

        orders = []
        for row in rows:
            row_id, name, phone, table_number, item_raw, total = row
            orders.append({
                "id": row_id,
                "name": name,
                "phone": phone,
                "table": table_number,
                "items": _jsonify_items(item_raw),
                "total": float(total or 0),
            })
        return jsonify(orders), 200
    except Exception as e:
        app.logger.exception("Error in /get-orders")
        return jsonify({"error": "Failed to retrieve orders"}), 500

# ---------------- Mark one order completed ----------------
@app.route("/delete-order/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE orders SET status = 'completed' WHERE id = %s;", (order_id,))
        return jsonify({"message": "Order marked as completed!"}), 200
    except Exception:
        app.logger.exception("Error in /delete-order")
        return jsonify({"error": "Failed to update order status"}), 500

# ---------------- Mark all orders completed ----------------
@app.route("/delete-all-orders", methods=["DELETE"])
def delete_all_orders():
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE orders SET status = 'completed' WHERE status IS DISTINCT FROM 'completed';")
        return jsonify({"message": "All orders marked as completed!"}), 200
    except Exception:
        app.logger.exception("Error in /delete-all-orders")
        return jsonify({"error": "Failed to update orders"}), 500

# ---------------- Delete one item & recalc total ----------------
@app.route("/delete-item/<int:order_id>/<int:item_index>", methods=["POST"])
def delete_item(order_id, item_index):
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT item FROM orders WHERE id = %s;", (order_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Order not found"}), 404

            items = _jsonify_items(row[0])
            if not (0 <= item_index < len(items)):
                return jsonify({"error": "Item index out of range"}), 400

            items.pop(item_index)

            if items:
                new_total = sum(float(i.get("price", 0)) for i in items)
                cur.execute(
                    "UPDATE orders SET item = %s, total = %s WHERE id = %s;",
                    (json.dumps(items, ensure_ascii=False), new_total, order_id),
                )
            else:
                cur.execute(
                    "UPDATE orders SET status = 'completed', total = 0 WHERE id = %s;",
                    (order_id,),
                )
        return jsonify({"message": "Item deleted and total updated!"}), 200
    except Exception:
        app.logger.exception("Error in /delete-item")
        return jsonify({"error": "Failed to delete item"}), 500

# ---------------- Order status by phone (or specific id) ----------------
@app.route("/order-status", methods=["GET"])
def order_status():
    phone    = request.args.get("phone")
    order_id = request.args.get("order", type=int)

    if not phone:
        return jsonify({"found": False, "error": "phone_required"}), 400

    try:
        with _conn() as conn, conn.cursor() as cur:
            if order_id:
                cur.execute("SELECT status FROM orders WHERE id=%s AND phone=%s;", (order_id, phone))
            else:
                cur.execute(
                    "SELECT status FROM orders WHERE phone=%s ORDER BY id DESC LIMIT 1;",
                    (phone,),
                )
            row = cur.fetchone()
        if row:
            return jsonify({"found": True, "status": row[0]}), 200
        return jsonify({"found": False}), 404
    except Exception:
        app.logger.exception("Error in /order-status")
        return jsonify({"found": False, "error": "server"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")), host="0.0.0.0")
