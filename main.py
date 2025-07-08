from flask import Flask, render_template, request, redirect, url_for
from pymongo import MongoClient
import json
import os
from bson.objectid import ObjectId
from dotenv import load_dotenv
import requests
from flask import flash, redirect, url_for


load_dotenv()
AFRO_TOKEN = os.getenv("AFRO_TOKEN")
AFRO_SENDER_ID = os.getenv("AFRO_SENDER_ID")


app = Flask(__name__)
DRIVERS_FILE = "drivers.json"

# MongoDB
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["tolo_delivery"]
deliveries_col = db["deliveries"]
drivers_ = client["drivers"]
drivers_col = drivers_["drivers"]

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
                'sender':'AfroMessage',
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


def load_drivers():
    try:
        with open(DRIVERS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print("Error reading drivers.json:", e)
        return []

@app.route("/update_delivery_type", methods=["POST"])
def update_delivery_type():
    try:
        delivery_id = request.form.get("delivery_id")
        delivery_type = request.form.get("delivery_type")

        if delivery_id and delivery_type:
            deliveries_col.update_one(
                {"_id": ObjectId(delivery_id)},
                {"$set": {"delivery_type": delivery_type}}
            )
            print(f"✅ Updated delivery type for {delivery_id} to {delivery_type}")
        else:
            print("⚠️ Missing delivery_id or delivery_type")

    except Exception as e:
        print("❌ Error updating delivery type:", e)

    return redirect(url_for("index"))


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

        deliveries = list(deliveries_col.find(query).sort("timestamp", -1))
        drivers = list(drivers_col.find())

        # Convert ObjectId to string and assign driver name
        for delivery in deliveries:
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

        return render_template("index.html", deliveries=deliveries, drivers=drivers, current_tab=filter_status or "pending")

    except Exception as e:
        print("❌ Error fetching data:", e)
        return render_template("index.html", deliveries=[], drivers=[], current_tab="pending")


@app.route("/assign_driver", methods=["POST"])
def assign_driver():
    try:
        delivery_id = request.form.get("delivery_id", "").strip()
        driver_id = request.form.get("driver_id", "").strip()

        if not delivery_id or not driver_id:
            return redirect(url_for("index"))

        delivery = deliveries_col.find_one({"_id": ObjectId(delivery_id)})
        if not delivery:
            return redirect(url_for("index"))

        driver = drivers_col.find_one({"_id": ObjectId(driver_id)})
        if not driver:
            return redirect(url_for("index"))

        # Assign driver
        deliveries_col.update_one(
            {"_id": ObjectId(delivery_id)},
            {"$set": {"assigned_driver_id": driver_id}}
        )

       
        print(f"Driver {driver.get('name', 'Unknown')} assigned to delivery {delivery_id}.")

    except Exception as e:
        print("❌ Error in assigning driver:", e)
   

    return redirect(url_for("index"))

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
            f"Location / ቦታ: {dropoff_location}\n"
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
            f"Thank you for choosing us. Tolo Delivery\n"
        )
        send_sms(phone_number=driver.get("phone", ""), message=message)
        send_sms(phone_number=senderphone, message=message_2)
        send_sms(phone_number=reciverphone, message=message_2)
    except Exception as e:
        print("❌ Error sending SMS to driver:", e)
        flash("Failed to send SMS.", "danger")

    return redirect(url_for("index"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(debug=False, host="0.0.0.0", port=port)
