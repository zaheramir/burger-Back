import os, json
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from dotenv import load_dotenv

# psycopg v3
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# For local runs; harmless on Railway where env vars are injected
load_dotenv()

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# -------- DB helpers --------
def get_db():
    if "db" not in g:
        # Railway URL already includes ?sslmode=require
        g.db = psycopg.connect(DATABASE_URL)
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# -------- Routes --------
@app.route("/", methods=["GET"])
def root():
    return {"ok": True}

@app.route("/favicon.ico")
def favicon():
    return ("", 204)

@app.route("/submit-order", methods=["POST"])
def submit_order():
    data = request.json or {}
    items = data.get("items") or []
    try:
        total = float(data.get("total") or 0)
    except Exception:
        total = 0.0

    sql = """
        INSERT INTO orders (name, phone, table_number, item, total, status)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    values = (
        (data.get("name") or "").strip(),
        (data.get("phone") or "").strip(),
        (data.get("table") or "").strip(),
        Jsonb(items),       # ✅ tell pg this is JSONB
        total,
        "pending",
    )

    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute(sql, values)
        new_id = cur.fetchone()[0]

    return jsonify({"message": "Order received successfully!", "order_id": new_id}), 200

@app.route("/get-orders", methods=["GET"])
def get_orders():
    conn = get_db()
    with conn.cursor(row_factory=dict_row) as cur:   # ✅ dict rows
        cur.execute("""
            SELECT id, name, phone, table_number, item, total
            FROM orders
            WHERE status != 'completed'
            ORDER BY id ASC
        """)
        rows = cur.fetchall()

    orders = []
    for row in rows:
        items = row["item"] or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        orders.append({
            "id": row["id"],
            "name": row["name"],
            "phone": row["phone"],
            "table": row["table_number"],
            "items": items,
            "total": float(row["total"] or 0),
        })
    return jsonify(orders), 200

@app.route("/delete-order/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = 'completed' WHERE id = %s", (order_id,))
    return jsonify({"message": "Order marked as completed!"}), 200

@app.route("/delete-all-orders", methods=["DELETE"])
def delete_all_orders():
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = 'completed' WHERE status != 'completed'")
    return jsonify({"message": "All orders marked as completed!"}), 200

@app.route("/delete-item/<int:order_id>/<int:item_index>", methods=["POST"])
def delete_item(order_id, item_index):
    conn = get_db()
    with conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT item FROM orders WHERE id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404

        items = row["item"] or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []

        if not (0 <= item_index < len(items)):
            return jsonify({"error": "Item index out of range"}), 400

        items.pop(item_index)
        if items:
            new_total = sum(float(i.get("price", 0)) for i in items)
            cur.execute(
                "UPDATE orders SET item = %s, total = %s WHERE id = %s",
                (Jsonb(items), new_total, order_id),
            )
        else:
            cur.execute(
                "UPDATE orders SET status = 'completed', total = 0, item = '[]'::jsonb WHERE id = %s",
                (order_id,),
            )
    return jsonify({"message": "Item deleted and total updated!"}), 200

@app.route("/order-status", methods=["GET"])
def order_status():
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"found": False, "error": "phone_required"}), 400
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM orders WHERE phone = %s ORDER BY id DESC LIMIT 1",
            (phone,),
        )
        row = cur.fetchone()
    if row:
        return jsonify({"found": True, "status": row[0]}), 200
    return jsonify({"found": False}), 404

if __name__ == "__main__":
    # Local dev only; Railway uses gunicorn via Procfile
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
