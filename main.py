from flask import Flask, render_template, request, redirect, url_for
from pymongo import MongoClient
import json
import os
from bson.objectid import ObjectId

app = Flask(__name__)
MESSAGES_FILE = "messages.json"
DRIVERS_FILE = "drivers.json"

# MongoDB Setup (adjust as needed)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["tolo_delivery"]
deliveries_col = db["deliveries"]
drivers_col = db["drivers"]

def load_deliveries():
    try:
        return list(deliveries_col.find())
    except Exception as e:
        print("Error fetching deliveries from MongoDB:", e)
        return []

def save_delivery(delivery):
    try:
        deliveries_col.insert_one(delivery)
    except Exception as e:
        print("Error saving delivery to MongoDB:", e)

def load_drivers():
    try:
        with open(DRIVERS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print("Error reading drivers.json:", e)
        return []

@app.route("/")
def index():
    deliveries = load_deliveries()
    print("Deliveries loaded:", deliveries)
    drivers = load_drivers()
    return render_template("/index.html", deliveries=deliveries, drivers=drivers)


@app.route("/assign_driver", methods=["POST"])
def assign_driver():
    try:
        delivery_id = request.form.get("delivery_id", "").strip()
        driver_id = request.form.get("driver_id", "").strip()

        if not delivery_id or not driver_id:
            raise ValueError("Missing delivery_id or driver_id")

        from bson import ObjectId
        deliveries_col.update_one(
            {"_id": ObjectId(delivery_id)},
            {"$set": {
                "assigned_driver_id": driver_id
            }}
        )
        print(f"Assigned driver {driver_id} to delivery {delivery_id}")
    except Exception as e:
        print("Error in assigning driver:", e)

    return redirect(url_for("index"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(debug=False, host="0.0.0.0", port=port)

