from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from pymongo import MongoClient
import json
import os
from bson.objectid import ObjectId
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
import re
from collections import Counter, defaultdict
from dateutil import parser
import pytz 


load_dotenv()
AFRO_TOKEN = os.getenv("AFRO_TOKEN")
AFRO_SENDER_ID = os.getenv("AFRO_SENDER_ID")


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
DRIVERS_FILE = "drivers.json"

# MongoDB
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["tolo_delivery"]
deliveries_col = db["deliveries"]
drivers_ = client["drivers"]
drivers_col = drivers_["drivers"]
feedback_col = db["feedback"]

def send_sms(phone_number, message):
    session = requests.Session()
    # base url
    base_url = 'https://api.afromessage.com/api/send'
    # api token
    token = AFRO_TOKEN
        # header
    headers = {'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'}
        # request body
    body = {'callback': 'YOUR_CALLBACK',
                'from': AFRO_SENDER_ID,
                'sender':'Tolo ET',
                'to': phone_number,
                'message': message}
        # make request
    result = session.post(base_url, json=body, headers=headers)
        # check result
    if result.status_code == 200:
        json_resp = result.json()
        print("🔍 Full JSON Response:", json_resp)  # ← ADD THIS LINE

        if json_resp.get('acknowledge') == 'success':
            print('✅ SMS sent successfully!')
        else:
            print('❌ API responded with error:', json_resp)

    else:
            # anything other than 200 goes here.
        print ('http error ... code: %d , msg: %s ' % (result.status_code, result.content))



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

@app.route("/delete_delivery/<delivery_id>", methods=["POST"])
def delete_delivery(delivery_id):
    try:
        deliveries_col.delete_one({"_id": ObjectId(delivery_id)})
        flash("✅ Delivery deleted successfully.", "success")
    except Exception as e:
        print("❌ Error deleting delivery:", e)
        flash("❌ Failed to delete delivery.", "danger")
    return redirect(url_for("index"))


@app.route("/update_delivery_type", methods=["POST"])
def update_delivery_type():
    try:
        data = request.get_json()
        delivery_id = data.get("delivery_id")
        delivery_type = data.get("delivery_type")

        deliveries_col.update_one(
            {"_id": ObjectId(delivery_id)},
            {"$set": {"delivery_type": delivery_type}}
        )
        return {"success": True}, 200
    except Exception as e:
        print("❌ Error updating delivery type:", e)
        return {"success": False, "error": str(e)}, 500


@app.route('/update_status/<delivery_id>/<new_status>', methods=['POST'])
def update_status(delivery_id, new_status):
    if new_status not in ['successful', 'unsuccessful']:
        flash('Invalid status value', 'danger')
        return redirect(url_for('index'))

    deliveries_col.update_one(
        {'_id': ObjectId(delivery_id)},
        {'$set': {'status': new_status}}
    )
    flash(f'Delivery status updated to {new_status}.', 'success')
    return redirect(url_for('index', filter_status=new_status))


@app.route("/")
@app.route("/status/<filter_status>")
def index(filter_status=None):
    try:
        query = {}
        if filter_status in ["successful", "unsuccessful", "pending"]:
            if filter_status == "pending":
                query["status"] = {"$in": [None, "", "pending"]}
            else:
                query["status"] = filter_status

        # Fetch deliveries matching filter
        deliveries = list(deliveries_col.find(query).sort("timestamp", -1))
        drivers = list(drivers_col.find())

        # Count by status
        pending_count = deliveries_col.count_documents({"status": {"$in": [None, "", "pending"]}})
        successful_count = deliveries_col.count_documents({"status": "successful"})
        unsuccessful_count = deliveries_col.count_documents({"status": "unsuccessful"})
        feedback_count = feedback_col.count_documents({})

        # Convert ObjectId to string and assign driver names
        for delivery in deliveries:
            delivery["price"] = delivery.get("price", None)
            delivery["_id"] = str(delivery["_id"])
            delivery["source"] = delivery.get("source", "unknown") 
            assigned_driver_id = delivery.get("assigned_driver_id")
            if assigned_driver_id:
                driver = drivers_col.find_one({"_id": ObjectId(assigned_driver_id)})
                delivery["assigned_driver_name"] = driver.get("name", "Unknown") if driver else "Unknown"
            else:
                delivery["assigned_driver_name"] = "Not Assigned"

        for driver in drivers:
            driver["id"] = str(driver["_id"])
            driver["name"] = driver.get("name", "Unnamed")

        return render_template(
            "index.html",
            deliveries=deliveries,
            drivers=drivers,
            current_tab=filter_status or "pending",
            pending_count=pending_count,
            successful_count=successful_count,
            unsuccessful_count=unsuccessful_count,
            feedback_count=feedback_count
        )

    except Exception as e:
        print("❌ Error fetching data:", e)
        return render_template(
            "index.html",
            deliveries=[],
            drivers=[],
            current_tab="pending",
            pending_count=0,
            successful_count=0,
            unsuccessful_count=0,
        )

@app.route("/assign_driver", methods=["POST"])
def assign_driver():
    try:
        data = request.get_json()
        delivery_id = data.get("delivery_id")
        driver_id = data.get("driver_id")

        delivery = deliveries_col.find_one({"_id": ObjectId(delivery_id)})
        driver = drivers_col.find_one({"_id": ObjectId(driver_id)})

        if not delivery or not driver:
            return {"success": False, "error": "Invalid delivery or driver"}, 400

        deliveries_col.update_one(
            {"_id": ObjectId(delivery_id)},
            {"$set": {"assigned_driver_id": driver_id}}
        )
        return {"success": True}, 200
    except Exception as e:
        print("❌ Error in assigning driver:", e)
        return {"success": False, "error": str(e)}, 500

@app.route("/notify_driver", methods=["POST"])
def notify_driver():
    try:
        delivery_id = request.form.get("delivery_id")
        delivery = deliveries_col.find_one({"_id": ObjectId(delivery_id)})

        if not delivery or not delivery.get("assigned_driver_id"):
            flash("No driver assigned to this delivery.", "warning")
            return redirect(url_for("index"))

        driver = drivers_col.find_one({"_id": ObjectId(delivery["assigned_driver_id"])})

        if not driver or not driver.get("phone"):
            flash("Driver phone number not found.", "danger")
            return redirect(url_for("index"))
       

        pickup_location = delivery.get("pickup", "N/A")
        senderphone = delivery.get("sender_phone", "N/A")
        dropoff_location = delivery.get("dropoff", "N/A")
        reciverphone = delivery.get("receiver_phone", "N/A")
        item = delivery.get("item_description", "N/A")
        quantity = delivery.get("Quantity", "N/A")
        price = delivery.get("price", "N/A")
        collect_from = delivery.get("payment_from_sender_or_receiver", "N/A")
        message = (
            f"New Delivery Order\n "
            f"------------------\n"
            f"from / ከ:{senderphone}\n"
            f"Location / ቦታ: {pickup_location }\n"
            f"To / ለ: {reciverphone}\n"
            f"Location / ቦታ:{dropoff_location}\n"
            f"Item / ዕቃ: {item}\n"
            f"Qty / ብዛት:{quantity}\n"
            f"Price / ዋጋ: {price}\n"
            f"Collect from / ክፍያ ከ: {collect_from}\n"

        )
        message_2 = (
            f"Your Driver Has Been Assigned / ውድ ደንበኛ፣ ሹፌርህ ተመድቧል።\n"
            f"Driver Name / የሾፌር ስም: {driver.get('name', 'N/A')}\n"
            f"Driver Phone / ሹፌር ስልክ: {driver.get('phone', 'N/A')}\n"
            f"license Plate / የመንጃ ፈቃድ ሰሌዳ: {driver.get('vehicle_plate', 'N/A')}\n"
            f"item / ዕቃ: {item}\n"
            f"Quantity / ብዛት: {quantity}\n"
            f"Price / ዋጋ: {price}\n"
            f"Thank you for choosing us. Tolo Delivery\n"
        )
        send_sms(phone_number=driver.get("phone", ""), message=message)
        send_sms(phone_number=senderphone, message=message_2)
        send_sms(phone_number=reciverphone, message=message_2)
    except Exception as e:
        print("❌ Error sending SMS to driver:", e)
        flash("Failed to send SMS.", "danger")

    return redirect(url_for("index"))

@app.route("/feedback")
def feedback_page():
    return render_template("feedback.html")

@app.route("/update_price", methods=["POST"])
def update_price():
    try:
        data = request.get_json()
        delivery_id = data.get("delivery_id")
        price = int(data.get("price"))

        deliveries_col.update_one(
            {"_id": ObjectId(delivery_id)},
            {"$set": {"price": price}}
        )
        return {"success": True}, 200
    except Exception as e:
        print("❌ Error updating price:", e)
        return {"success": False, "error": str(e)}, 500


@app.route("/view_feedback")
def view_feedback():
    try:
        feedbacks = list(feedback_col.find().sort("_id", -1))  # recent first
        for fb in feedbacks:
            fb["_id"] = str(fb["_id"])  # Convert ObjectId to string
        return render_template("view_feedback.html", feedbacks=feedbacks)
    except Exception as e:
        print("❌ Error fetching feedback:", e)
        return render_template("view_feedback.html", feedbacks=[])



def is_valid_ethiopian_number(phone):
    return re.fullmatch(r'(\+251|0)9\d{8}', phone)

@app.route('/add_delivery', methods=['GET', 'POST'])
def add_delivery_page():
    if request.method == 'POST':
        data = {
            "user_name": request.form.get("user_name"),
            "pickup": request.form.get("pickup"),
            "dropoff": request.form.get("dropoff"),
            "sender_phone": request.form.get("sender_phone"),
            "receiver_phone": request.form.get("receiver_phone"),
            "full_address": request.form.get("full_address"),
            "payment_from_sender_or_receiver": request.form.get("payment_from_sender_or_receiver"),
            "item_description": request.form.get("item_description"),
            "Quantity": int(request.form.get("quantity")),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "delivery_type": None,
            "assigned_driver_name": "Not Assigned",
            "status": "pending",
            "source": "web"
        }

        if not is_valid_ethiopian_number(data["sender_phone"]) or not is_valid_ethiopian_number(data["receiver_phone"]):
            flash("❌ Invalid phone number format", "danger")
            return redirect(url_for('add_delivery_page'))

        deliveries_col.insert_one(data)
        flash("✅ Delivery added successfully!", "success")
        return redirect(url_for('index'))

    return render_template('add_delivery.html')



@app.route('/statistics')
def statistics():
    deliveries = list(db.deliveries.find({}))
    users = list(db.users.find({}))  # Make sure you have this collection

    today = datetime.utcnow().date()
    days = [today - timedelta(days=i) for i in reversed(range(30))]
    registrations_per_day = {d.strftime('%Y-%m-%d'): 0 for d in days}

    for user in users:
        reg_date = user.get('created_at')
        if reg_date:
            # If reg_date is string, parse it to datetime
            if isinstance(reg_date, str):
                try:
                    reg_date_dt = parser.parse(reg_date)
                except Exception as e:
                    print(f"Error parsing created_at for user: {e}")
                    continue
            elif isinstance(reg_date, datetime):
                reg_date_dt = reg_date
            else:
                continue  # unknown format, skip
            
            reg_date_str = reg_date_dt.strftime('%Y-%m-%d')
            if reg_date_str in registrations_per_day:
                registrations_per_day[reg_date_str] += 1

    # Other stats...
    status_counts = Counter(d.get('status', 'pending') for d in deliveries)
    service_type_counts = Counter(d.get('delivery_type', 'Not Set') for d in deliveries)
    driver_counts = Counter(d.get('assigned_driver_name', 'Not Assigned') for d in deliveries)
    user_counts = Counter(d.get('user_name', 'Unknown') for d in deliveries)
    top_users = user_counts.most_common(5)

    route_stats = {
        "average_route_km": 12.5,
        "optimized_routes": 150,
        "non_optimized_routes": 30
    }

    return render_template('statistics.html',
                           registrations_per_day=registrations_per_day,
                           status_counts=status_counts,
                           service_type_counts=service_type_counts,
                           driver_counts=driver_counts,
                           top_users=top_users,
                           route_stats=route_stats)



@app.route('/map')
def map_view():
    deliveries_with_location = list(deliveries_col.find({
        "latitude": {"$exists": True},
        "longitude": {"$exists": True}
    }))

    return render_template('map.html', deliveries=deliveries_with_location)


@app.route("/old_deliveries")
def old_deliveries():
    try:
        # Define your local timezone here; example: East Africa Time (EAT) UTC+3
        local_tz = pytz.timezone("Africa/Addis_Ababa")

        # Current local time
        now_local = datetime.now(local_tz)

        # 12 hours ago local time
        cutoff_time = now_local - timedelta(hours=12)

        # Convert cutoff_time to string in your timestamp format for query
        # Your timestamp format: "%Y-%m-%d %H:%M:%S"
        cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")

        # Fetch deliveries older than cutoff_time
        # Your timestamps are strings so we do string comparison (works if format is ISO-like)
        old_deliveries = list(deliveries_col.find({
            "timestamp": {"$lt": cutoff_str}
        }).sort("timestamp", -1))

        # Convert ObjectId to string and assign driver names as in index()
        drivers = list(drivers_col.find())

        for delivery in old_deliveries:
            delivery["_id"] = str(delivery["_id"])
            assigned_driver_id = delivery.get("assigned_driver_id")
            if assigned_driver_id:
                driver = drivers_col.find_one({"_id": ObjectId(assigned_driver_id)})
                delivery["assigned_driver_name"] = driver.get("name", "Unknown") if driver else "Unknown"
            else:
                delivery["assigned_driver_name"] = "Not Assigned"

        return render_template("old_deliveries.html", deliveries=old_deliveries)

    except Exception as e:
        print("❌ Error fetching old deliveries:", e)
        return render_template("old_deliveries.html", deliveries=[])


if __name__ == "__main__":  
    port = int(os.environ.get("PORT", 3000))
    app.run(debug=False, host="0.0.0.0", port=port)
