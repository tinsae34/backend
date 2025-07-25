from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient
import json
import os
from bson.objectid import ObjectId
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
import re

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

@app.route("/statistics")
def statistics():
    try:
        now = datetime.now()
        start_of_week = now - timedelta(days=now.weekday())  # Monday
        start_of_month = now.replace(day=1)

        # Fetch deliveries
        deliveries = list(deliveries_col.find())

        # Init counters
        weekly_count = 0
        monthly_count = 0
        weekly_status = {"pending": 0, "successful": 0, "unsuccessful": 0}
        monthly_status = {"pending": 0, "successful": 0, "unsuccessful": 0}
        source_counts = {"bot": 0, "web": 0, "unknown": 0}

        for d in deliveries:
            try:
                timestamp = datetime.strptime(d.get("timestamp"), "%Y-%m-%d %H:%M:%S")
            except:
                continue

            status = d.get("status", "pending")
            source = d.get("source", "unknown")

            if timestamp >= start_of_week:
                weekly_count += 1
                weekly_status[status] = weekly_status.get(status, 0) + 1

            if timestamp >= start_of_month:
                monthly_count += 1
                monthly_status[status] = monthly_status.get(status, 0) + 1

            source_counts[source] = source_counts.get(source, 0) + 1

        return render_template("statistic 3 s.html",
                               weekly_count=weekly_count,
                               monthly_count=monthly_count,
                               weekly_status=weekly_status,
                               monthly_status=monthly_status,
                               source_counts=source_counts)
    except Exception as e:
        print("❌ Error loading statistics:", e)
        return "Error loading statistics"

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
    return redirect(url_for('index', filter_status='pending'))  # adjust as needed



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
            flash("⚠️ No driver assigned to this delivery.", "warning")
            return redirect(url_for("index"))

        driver = drivers_col.find_one({"_id": ObjectId(delivery["assigned_driver_id"])})

        if not driver or not driver.get("phone"):
            flash("❌ Driver phone number not found.", "danger")
            return redirect(url_for("index"))

        # Build SMS messages
        pickup_location = delivery.get("pickup", "N/A")
        senderphone = delivery.get("sender_phone", "N/A")
        dropoff_location = delivery.get("dropoff", "N/A")
        reciverphone = delivery.get("receiver_phone", "N/A")
        item = delivery.get("item_description", "N/A")
        quantity = delivery.get("Quantity", "N/A")
        price = delivery.get("price", "N/A")
        collect_from = delivery.get("payment_from_sender_or_receiver", "N/A")

        message = (
            f"New Delivery Order\n"
            f"------------------\n"
            f"from / ከ:{senderphone}\n"
            f"Location / ቦታ: {pickup_location}\n"
            f"To / ለ: {reciverphone}\n"
            f"Location / ቦታ: {dropoff_location}\n"
            f"Item / ዕቃ: {item}\n"
            f"Qty / ብዛት: {quantity}\n"
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

       
        success1, msg1 = send_sms(phone_number=driver.get("phone", ""), message=message)
        success2, msg2 = send_sms(phone_number=senderphone, message=message_2)
        success3, msg3 = send_sms(phone_number=reciverphone, message=message_2)

        if success1 and success2 and success3:
            flash("✅ SMS notifications sent to driver, sender, and receiver.", "success")
        else:
            flash("⚠️ Some SMS messages failed to send.", "warning")
            if not success1: flash(f"Driver SMS error: {msg1}", "danger")
            if not success2: flash(f"Sender SMS error: {msg2}", "danger")
            if not success3: flash(f"Receiver SMS error: {msg3}", "danger")

    except Exception as e:
        print("❌ Error sending SMS to driver:", e)
        flash("❌ Failed to send SMS due to an error.", "danger")

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(debug=False, host="0.0.0.0", port=port)
