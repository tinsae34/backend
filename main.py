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
import pytz  # You may need to install pytz with `pip install pytz`


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

bot_events_col = db.bot_events     
deliveries_col = db.deliveries 

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

from collections import defaultdict, Counter
from dateutil import parser
from datetime import datetime, timedelta



@app.route("/statistics")
def statistics():
    try:
        # Active tab (default to 'daily')
        active_tab = request.args.get("tab", "daily")

        # Separate day filters with fallback to 30
        try:
            days_daily = int(request.args.get("days_daily", 30))
        except (TypeError, ValueError):
            days_daily = 30

        try:
            days_drivers = int(request.args.get("days_drivers", 30))
        except (TypeError, ValueError):
            days_drivers = 30

        now = datetime.now()

        # Calculate cutoff times for daily and drivers filtering
        since_daily = now - timedelta(days=days_daily)
        since_drivers = now - timedelta(days=days_drivers)

        deliveries = list(deliveries_col.find({}))
        drivers = list(drivers_col.find({}))

        total_users = len(set(d.get("sender_phone") for d in deliveries if "sender_phone" in d))

        daily_counts = defaultdict(int)
        status_counts = Counter()
        type_counts = Counter()
        driver_stats = defaultdict(int)

        sender_counts = defaultdict(lambda: {"sent": 0, "location": "Unknown"})
        receiver_counts = defaultdict(lambda: {"received": 0, "location": "Unknown"})

        for d in deliveries:
            ts = d.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = parser.parse(ts)
                except Exception:
                    continue
            if not isinstance(ts, datetime):
                continue

            # Filter for daily stats by days_daily
            if ts >= since_daily:
                day = ts.strftime("%Y-%m-%d")
                daily_counts[day] += 1
                status_counts[d.get("status", "pending")] += 1
                delivery_type = (d.get("delivery_type") or "").lower()
                if delivery_type in ["payable", "free"]:
                    type_counts[delivery_type] += 1
                else:
                    type_counts["unknown"] += 1

                # Track sender/receiver for daily filter range only
                sender = d.get("sender_phone")
                receiver = d.get("receiver_phone")
                if sender:
                    sender_counts[sender]["sent"] += 1
                    sender_counts[sender]["location"] = d.get("pickup", "Unknown")
                if receiver:
                    receiver_counts[receiver]["received"] += 1
                    receiver_counts[receiver]["location"] = d.get("dropoff", "Unknown")

            # Filter for driver stats by days_drivers
            if ts >= since_drivers:
                driver_id = d.get("assigned_driver_id")
                if driver_id:
                    driver_stats[str(driver_id)] += 1

        daily_counts = dict(sorted(daily_counts.items()))
        driver_name_map = {str(d["_id"]): d.get("name", "Unnamed") for d in drivers}
        driver_delivery_data = {
            driver_name_map.get(driver_id, "Unknown"): count
            for driver_id, count in driver_stats.items()
        }

        # Top senders/receivers based on daily_counts range
        top_senders = sorted([
            {"phone": phone, "sent": data["sent"], "location": data["location"]}
            for phone, data in sender_counts.items()
        ], key=lambda x: x["sent"], reverse=True)[:10]

        top_receivers = sorted([
            {"phone": phone, "received": data["received"], "location": data["location"]}
            for phone, data in receiver_counts.items()
        ], key=lambda x: x["received"], reverse=True)[:10]

        # Combine all customers (senders + receivers)
        all_customers = {}
        for phone, data in sender_counts.items():
            all_customers[phone] = {
                "phone": phone,
                "location": data["location"],
                "sent": data["sent"],
                "received": 0,
                "total": data["sent"]
            }
        for phone, data in receiver_counts.items():
            if phone in all_customers:
                all_customers[phone]["received"] = data["received"]
                all_customers[phone]["total"] += data["received"]
            else:
                all_customers[phone] = {
                    "phone": phone,
                    "location": data["location"],
                    "sent": 0,
                    "received": data["received"],
                    "total": data["received"]
                }

        all_customers_list = sorted(all_customers.values(), key=lambda x: x["total"], reverse=True)

        return render_template("statistics.html",
                               active_tab=active_tab,
                               days_daily=days_daily,
                               days_drivers=days_drivers,
                               daily_counts=daily_counts,
                               status_counts=status_counts,
                               type_counts=type_counts,
                               driver_delivery_data=driver_delivery_data,
                               total_users=total_users,
                               top_senders=top_senders,
                               top_receivers=top_receivers,
                               all_customers=all_customers_list)

    except Exception as e:
        print("❌ Error building statistics:", e)
        return render_template("statistics.html", error=str(e))

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.units import inch
from io import BytesIO

@app.route("/statistics/export_pdf")
def export_registration_report_pdf():
    try:
        days = int(request.args.get("days", 30))
        now = datetime.now()
        since = now - timedelta(days=days)

        deliveries = list(deliveries_col.find({}))
        drivers = list(drivers_col.find({}))

        total_registrations = 0
        daily_trends = defaultdict(int)
        service_type_counts = Counter()
        location_counts = Counter()
        driver_success = defaultdict(lambda: {"total": 0, "successful": 0})

        for d in deliveries:
            ts = d.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = parser.parse(ts)
                except Exception:
                    continue
            if not isinstance(ts, datetime) or ts < since:
                continue

            total_registrations += 1
            date_str = ts.strftime("%Y-%m-%d")
            daily_trends[date_str] += 1

            service_type = (d.get("delivery_type") or "unknown").lower()
            if service_type in ["payable", "free"]:
                service_type_counts[service_type] += 1
            else:
                service_type_counts["unknown"] += 1

            location = d.get("pickup") or "Unknown"
            location_counts[location] += 1

            driver_id = d.get("assigned_driver_id")
            if driver_id:
                driver_success[driver_id]["total"] += 1
                if d.get("status") == "successful":
                    driver_success[driver_id]["successful"] += 1

        # Start PDF generation
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph(f"📋 <b>Registration Analytics Report (Last {days} Days)</b>", styles["Title"]))
        elements.append(Spacer(1, 0.2 * inch))

        def add_table(title, headers, rows):
            elements.append(Paragraph(f"<b>{title}</b>", styles["Heading3"]))
            data = [headers] + rows
            table = Table(data, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.3 * inch))

        # Section 1: Overall Summary
        summary_data = [
            ("Total Registrations", total_registrations),
            ("Total Drivers", len(drivers)),
            ("Unique Locations", len(location_counts)),
            ("Total Payable", service_type_counts["payable"]),
            ("Total Free", service_type_counts["free"]),
        ]
        add_table("🔹 Overall Summary", ["Metric", "Count"], summary_data)

        # Section 2: Daily Registration Trends
        daily_rows = sorted(daily_trends.items())
        add_table("📅 Daily Registration Trends", ["Date", "Registrations"], daily_rows)

        # Section 3: Service Type Analysis
        total_service = sum(service_type_counts.values())
        service_rows = [
            (stype.title(), count, f"{(count / total_service * 100):.1f}%")
            for stype, count in service_type_counts.items()
        ]
        add_table("🛠 Service Type Analysis", ["Type", "Count", "Percentage"], service_rows)

        # Section 4: Driver Performance
        driver_map = {str(d["_id"]): d.get("name", "Unnamed") for d in drivers}
        driver_rows = []
        for driver_id, stats in driver_success.items():
            name = driver_map.get(str(driver_id), "Unknown")
            total = stats["total"]
            success = stats["successful"]
            rate = f"{(success / total * 100):.1f}%" if total else "0%"
            driver_rows.append((name, total, success, rate))
        add_table("🧑‍✈️ Driver Performance", ["Driver", "Total", "Successful", "Success Rate"], driver_rows)

        # Section 5: Location Analysis
        total_locations = sum(location_counts.values())
        loc_rows = [
            (loc, count, f"{(count / total_locations * 100):.1f}%")
            for loc, count in sorted(location_counts.items(), key=lambda x: -x[1])
        ]
        add_table("📍 Location Analysis", ["Location", "Registrations", "Percentage"], loc_rows)

        # Build and return
        doc.build(elements)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name="registration_report.pdf", mimetype="application/pdf")

    except Exception as e:
        print("❌ PDF generation error:", e)
        return "Error generating PDF", 500



from reportlab.pdfgen import canvas

from dateutil import parser
from datetime import datetime, timedelta




@app.route("/statistics/export_daily_pdf")
def export_daily_pdf():
    try:
        days = int(request.args.get("days", 30))
        now = datetime.now()
        since = now - timedelta(days=days)

        deliveries = list(deliveries_col.find({}))  # Python-side timestamp filtering

        daily_stats = defaultdict(lambda: {
            "successful": 0,
            "unsuccessful": 0,
            "birr_100": 0,
            "birr_200": 0,
            "birr_300": 0,
            "total_price": 0
        })

        total_money_this_period = 0

        for d in deliveries:
            ts = d.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = parser.parse(ts)
                except Exception:
                    continue
            if not isinstance(ts, datetime) or ts < since:
                continue

            day = ts.strftime("%Y-%m-%d")
            status = d.get("status", "pending").lower()
            price = int(d.get("price", 0))

            if status == "successful":
                daily_stats[day]["successful"] += 1

                if price == 100:
                    daily_stats[day]["birr_100"] += 1
                elif price == 200:
                    daily_stats[day]["birr_200"] += 1
                elif price == 300:
                    daily_stats[day]["birr_300"] += 1

                daily_stats[day]["total_price"] += price
                total_money_this_period += price

            elif status == "unsuccessful":
                daily_stats[day]["unsuccessful"] += 1

        sorted_days = sorted(daily_stats.keys())

        # ✅ Accurate TOTAL row calculation
        total_stats = {
            "successful": 0,
            "unsuccessful": 0,
            "birr_100": 0,
            "birr_200": 0,
            "birr_300": 0,
            "total": 0,
            "total_price": 0
        }

        for stats in daily_stats.values():
            total_stats["successful"] += stats.get("successful", 0)
            total_stats["unsuccessful"] += stats.get("unsuccessful", 0)
            total_stats["birr_100"] += stats.get("birr_100", 0)
            total_stats["birr_200"] += stats.get("birr_200", 0)
            total_stats["birr_300"] += stats.get("birr_300", 0)
            total_stats["total_price"] += stats.get("total_price", 0)

        total_stats["total"] = total_stats["successful"] + total_stats["unsuccessful"]

        # ✅ Optional debug
        print("✅ TOTAL STATS:", total_stats)

        # Generate PDF
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 40

        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, f"📅 Daily Registrations Report (Last {days} Days)")
        y -= 25

        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, f"💰 Total Money This Period: {total_money_this_period} Br")
        y -= 30

        headers = ["Date", "✔️", "❌", "100 Br", "200 Br", "300 Br", "Total", "Total Price"]
        x_positions = [50, 100, 140, 180, 230, 290, 350, 430]

        p.setFont("Helvetica-Bold", 9)
        for i, header in enumerate(headers):
            p.drawString(x_positions[i], y, header)
        y -= 15
        p.line(50, y, width - 50, y)
        y -= 20

        p.setFont("Helvetica", 9)
        for day in sorted_days:
            stats = daily_stats[day]
            values = [
                day,
                str(stats["successful"]),
                str(stats["unsuccessful"]),
                str(stats["birr_100"]),
                str(stats["birr_200"]),
                str(stats["birr_300"]),
                str(stats["successful"] + stats["unsuccessful"]),
                f"{stats['total_price']} Br"
            ]
            for i, val in enumerate(values):
                p.drawString(x_positions[i], y, val)
            y -= 18

            if y < 80:
                p.showPage()
                y = height - 40
                p.setFont("Helvetica-Bold", 9)
                for i, header in enumerate(headers):
                    p.drawString(x_positions[i], y, header)
                y -= 15
                p.line(50, y, width - 50, y)
                y -= 20
                p.setFont("Helvetica", 9)

        # TOTAL row
        if y < 80:
            p.showPage()
            y = height - 40
            p.setFont("Helvetica-Bold", 9)
            for i, header in enumerate(headers):
                p.drawString(x_positions[i], y, header)
            y -= 15
            p.line(50, y, width - 50, y)
            y -= 20

        p.setFont("Helvetica-Bold", 9)
        p.drawString(50, y, "TOTAL")
        p.drawString(100, y, str(total_stats["successful"]))
        p.drawString(140, y, str(total_stats["unsuccessful"]))
        p.drawString(180, y, str(total_stats["birr_100"]))
        p.drawString(230, y, str(total_stats["birr_200"]))
        p.drawString(290, y, str(total_stats["birr_300"]))
        p.drawString(350, y, str(total_stats["total"]))
        p.drawString(430, y, f"{total_stats['total_price']} Br")

        p.showPage()
        p.save()
        buffer.seek(0)

        filename = f"daily_registrations_report_{now.strftime('%Y-%m-%d')}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    except Exception as e:
        print("❌ Error generating daily registrations PDF:", e)
        return "Error generating PDF", 500

@app.route("/statistics/export_driver_pdf")
def export_driver_report_pdf():
    try:
        days = int(request.args.get("days", 30))
        now = datetime.now()
        since = now - timedelta(days=days)

        deliveries = list(deliveries_col.find({}))
        drivers = list(drivers_col.find({}))

        driver_stats = defaultdict(lambda: {
            "count": 0,
            "total_price": 0,
            "birr_100": 0,
            "birr_200": 0,
            "birr_300": 0,
        })

        driver_daily_breakdown = defaultdict(lambda: defaultdict(int))

        for d in deliveries:
            ts = d.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = parser.parse(ts)
                except Exception:
                    continue
            if not isinstance(ts, datetime) or ts < since:
                continue
            if d.get("status", "").lower() != "successful":
                continue
            

            driver_id = d.get("assigned_driver_id")
            price = int(d.get("price", 0))
            if driver_id:
                driver_stats[str(driver_id)]["count"] += 1
                driver_stats[str(driver_id)]["total_price"] += price

                if price == 100:
                    driver_stats[str(driver_id)]["birr_100"] += 1
                elif price == 200:
                    driver_stats[str(driver_id)]["birr_200"] += 1
                elif price == 300:
                    driver_stats[str(driver_id)]["birr_300"] += 1

                date_str = ts.strftime("%Y-%m-%d")
                driver_daily_breakdown[str(driver_id)][date_str] += 1

        driver_name_map = {str(d["_id"]): d.get("name", "Unnamed") for d in drivers}
        avg_days = max(days, 1)

        # Build full date list for the report period
        date_list = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

        # Generate PDF
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 40

        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, f"🧑‍✈️ Successful Deliveries Report (Last {days} Days)")
        y -= 30

        # Summary Table
        p.setFont("Helvetica-Bold", 10)
        headers = ["Driver", "100 Br", "200 Br", "300 Br", "Total Deliveries", "Total Price", "Avg/Day"]
        x_positions = [50, 160, 210, 260, 320, 420, 500]
        for i, header in enumerate(headers):
            p.drawString(x_positions[i], y, header)
        y -= 20

        p.setFont("Helvetica", 9)

        totals = {"birr_100": 0, "birr_200": 0, "birr_300": 0, "count": 0, "total_price": 0}

        for driver_id, stats in driver_stats.items():
            if y < 120:
                p.showPage()
                y = height - 40
                p.setFont("Helvetica-Bold", 10)
                for i, header in enumerate(headers):
                    p.drawString(x_positions[i], y, header)
                y -= 20
                p.setFont("Helvetica", 9)

            name = driver_name_map.get(driver_id, "Unknown")
            count_100 = stats["birr_100"]
            count_200 = stats["birr_200"]
            count_300 = stats["birr_300"]
            total = stats["count"]
            total_price = stats["total_price"]
            avg_per_day = total / avg_days

            p.drawString(x_positions[0], y, str(name))
            p.drawRightString(x_positions[1] + 30, y, str(count_100))
            p.drawRightString(x_positions[2] + 30, y, str(count_200))
            p.drawRightString(x_positions[3] + 30, y, str(count_300))
            p.drawRightString(x_positions[4] + 40, y, str(total))
            p.drawRightString(x_positions[5] + 60, y, f"{total_price} Br")
            p.drawRightString(x_positions[6] + 40, y, f"{avg_per_day:.2f}")
            y -= 15

            totals["birr_100"] += count_100
            totals["birr_200"] += count_200
            totals["birr_300"] += count_300
            totals["count"] += total
            totals["total_price"] += total_price

        # TOTAL ROW
        p.setFont("Helvetica-Bold", 9)
        p.drawString(x_positions[0], y, "TOTAL")
        p.drawRightString(x_positions[1] + 30, y, str(totals["birr_100"]))
        p.drawRightString(x_positions[2] + 30, y, str(totals["birr_200"]))
        p.drawRightString(x_positions[3] + 30, y, str(totals["birr_300"]))
        p.drawRightString(x_positions[4] + 40, y, str(totals["count"]))
        p.drawRightString(x_positions[5] + 60, y, f"{totals['total_price']} Br")
        p.drawRightString(x_positions[6] + 40, y, f"{totals['count'] / avg_days:.2f}")
        y -= 30

        # Daily Breakdown Section
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, "📅 Daily Breakdown per Driver")
        y -= 25

        for driver_id, daily_counts in driver_daily_breakdown.items():
            if y < 80:
                p.showPage()
                y = height - 40
            name = driver_name_map.get(driver_id, "Unknown")
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, f"Driver: {name}")
            y -= 20

            p.setFont("Helvetica-Bold", 10)
            p.drawString(60, y, "Date")
            p.drawString(200, y, "Deliveries")
            y -= 15

            p.setFont("Helvetica", 10)
            for date_str in date_list:
                if y < 80:
                    p.showPage()
                    y = height - 40
                count = daily_counts.get(date_str, 0)
                p.drawString(60, y, date_str)
                p.drawString(200, y, str(count))
                y -= 15
            y -= 20

        p.showPage()
        p.save()
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name="successful_deliveries_report.pdf", mimetype="application/pdf")

    except Exception as e:
        print("❌ PDF generation error (driver report):", e)
        return "Error generating PDF", 500


@app.route("/statistics/export_user_pdf")
def export_user_pdf():
    try:
        deliveries = list(deliveries_col.find({}))

        sender_counts = defaultdict(lambda: {"sent": 0, "location": "Unknown"})
        receiver_counts = defaultdict(lambda: {"received": 0, "location": "Unknown"})

        for d in deliveries:
            sender = d.get("sender_phone")
            receiver = d.get("receiver_phone")
            if sender:
                sender_counts[sender]["sent"] += 1
                sender_counts[sender]["location"] = d.get("pickup", "Unknown")
            if receiver:
                receiver_counts[receiver]["received"] += 1
                receiver_counts[receiver]["location"] = d.get("dropoff", "Unknown")

        all_customers = {}
        for phone, data in sender_counts.items():
            all_customers[phone] = {
                "phone": phone,
                "location": data["location"],
                "sent": data["sent"],
                "received": 0,
                "total": data["sent"]
            }
        for phone, data in receiver_counts.items():
            if phone in all_customers:
                all_customers[phone]["received"] = data["received"]
                all_customers[phone]["total"] += data["received"]
            else:
                all_customers[phone] = {
                    "phone": phone,
                    "location": data["location"],
                    "sent": 0,
                    "received": data["received"],
                    "total": data["received"]
                }

        sorted_customers = sorted(all_customers.values(), key=lambda x: x["total"], reverse=True)

        # PDF Generation
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 40

        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, "👥 Most Active Users Report")
        y -= 30

        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, "Phone")
        p.drawString(150, y, "Location")
        p.drawString(300, y, "Sent")
        p.drawString(360, y, "Received")
        p.drawString(440, y, "Total")
        y -= 15
        p.line(40, y, width - 40, y)
        y -= 20

        p.setFont("Helvetica", 10)
        for user in sorted_customers:
            if y < 60:
                p.showPage()
                y = height - 40
                p.setFont("Helvetica-Bold", 12)
                p.drawString(40, y, "Phone")
                p.drawString(150, y, "Location")
                p.drawString(300, y, "Sent")
                p.drawString(360, y, "Received")
                p.drawString(440, y, "Total")
                y -= 15
                p.line(40, y, width - 40, y)
                y -= 20
                p.setFont("Helvetica", 10)

            p.drawString(40, y, user["phone"])
            p.drawString(150, y, user["location"])
            p.drawString(300, y, str(user["sent"]))
            p.drawString(360, y, str(user["received"]))
            p.drawString(440, y, str(user["total"]))
            y -= 18

        p.save()
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name="most_active_users.pdf", mimetype="application/pdf")

    except Exception as e:
        print("❌ Error generating user PDF:", e)
        return "Error generating PDF", 500


from flask import render_template
from datetime import datetime, timedelta

@app.route("/admin/stats")
def admin_stats():
    now = datetime.now()
    start_of_day = datetime(now.year, now.month, now.day)
    start_of_week = now - timedelta(days=now.weekday())  # Monday
    start_of_week = datetime(start_of_week.year, start_of_week.month, start_of_week.day)

    total_starts = db.bot_events.count_documents({"event": "bot_start"})
    total_fallbacks = db.bot_events.count_documents({"event": "fallback"})

    daily_starts = db.bot_events.count_documents({
        "event": "bot_start",
        "timestamp": {"$gte": start_of_day}
    })

    weekly_deliveries = list(db.deliveries.find({
        "timestamp": {"$gte": start_of_week.strftime("%Y-%m-%d")}
    }))

    total_made = 0
    for d in weekly_deliveries:
        if d.get("is_free_delivery"):
            continue
        price_text = d.get("price", "")
        try:
            price = int(str(price_text).strip().split()[0])
            total_made += price
        except:
            continue

    return render_template("admin.html", 
        total_starts=total_starts,
        total_fallbacks=total_fallbacks,
        daily_starts=daily_starts,
        total_made=total_made
    )

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
