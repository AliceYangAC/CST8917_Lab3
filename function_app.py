# =============================================================================
# FleetBook — Booking Evaluation Azure Function
# CST8917 Lab 3 — Service Bus, Logic Apps & Azure Functions
# =============================================================================
# This Azure Function is called by the Logic App to evaluate booking requests.
# It checks vehicle availability, calculates pricing, and returns a decision.
# =============================================================================

import azure.functions as func
import json
import logging
from datetime import datetime

# =============================================================================
# CREATE THE FUNCTION APP
# =============================================================================
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# =============================================================================
# FLEET DATA (mock telematic database)
# =============================================================================
# In production this would come from a database or fleet management API.
# Each vehicle has real-time telematic info: location, availability, mileage,
# and a daily rental rate.

FLEET = [
    {"id": "V001", "type": "sedan",  "available": True,  "location": "Ottawa",    "mileage": 25000, "dailyRate": 45},
    {"id": "V002", "type": "SUV",    "available": True,  "location": "Toronto",   "mileage": 18000, "dailyRate": 75},
    {"id": "V003", "type": "sedan",  "available": False, "location": "Montreal",  "mileage": 42000, "dailyRate": 45},
    {"id": "V004", "type": "truck",  "available": True,  "location": "Ottawa",    "mileage": 31000, "dailyRate": 65},
    {"id": "V005", "type": "SUV",    "available": False, "location": "Toronto",   "mileage": 55000, "dailyRate": 75},
    {"id": "V006", "type": "van",    "available": True,  "location": "Vancouver", "mileage": 12000, "dailyRate": 85},
    {"id": "V007", "type": "sedan",  "available": True,  "location": "Calgary",   "mileage": 8000,  "dailyRate": 45},
    {"id": "V008", "type": "truck",  "available": False, "location": "Ottawa",    "mileage": 67000, "dailyRate": 65},
    {"id": "V009", "type": "SUV",    "available": True,  "location": "Ottawa",    "mileage": 14000, "dailyRate": 75},
    {"id": "V010", "type": "sedan",  "available": True,  "location": "Toronto",   "mileage": 5000,  "dailyRate": 50},
]

# =============================================================================
# PRICING LOGIC
# =============================================================================

def calculate_price(daily_rate, pickup_date_str, return_date_str, notes):
    """Calculate total rental price with optional add-ons."""
    try:
        pickup = datetime.strptime(pickup_date_str, "%Y-%m-%d")
        ret = datetime.strptime(return_date_str, "%Y-%m-%d")
        days = max((ret - pickup).days, 1)
    except (ValueError, TypeError):
        days = 1

    base_price = daily_rate * days

    # Add-on pricing based on special requests
    add_ons = []
    add_on_total = 0
    if notes:
        notes_lower = notes.lower()
        if "child seat" in notes_lower or "car seat" in notes_lower:
            add_ons.append("Child seat ($10/day)")
            add_on_total += 10 * days
        if "gps" in notes_lower:
            add_ons.append("GPS ($5/day)")
            add_on_total += 5 * days
        if "insurance" in notes_lower:
            add_ons.append("Insurance upgrade ($15/day)")
            add_on_total += 15 * days

    # Weekly discount: 10% off for 7+ days
    discount = 0
    if days >= 7:
        discount = round(base_price * 0.10, 2)

    total = base_price + add_on_total - discount

    return {
        "days": days,
        "dailyRate": daily_rate,
        "basePrice": base_price,
        "addOns": add_ons,
        "addOnTotal": add_on_total,
        "discount": discount,
        "estimatedPrice": round(total, 2)
    }


# =============================================================================
# CHECK BOOKING FUNCTION
# =============================================================================
# Decision logic:
#   1. Find vehicles matching type and pickup location
#   2. Filter to only available vehicles
#   3. If match found → CONFIRMED (pick lowest mileage vehicle)
#   4. If no match → REJECTED with a specific reason
#   5. Calculate pricing for confirmed bookings

@app.function_name(name="check-booking")
@app.route(route="", methods=["POST"])
def check_booking(req: func.HttpRequest) -> func.HttpResponse:
    """
    Evaluate a booking request against fleet telematic data.

    Expected JSON body:
    {
        "bookingId": "BK-0001",
        "customerName": "Jane Doe",
        "customerEmail": "jane@example.com",
        "vehicleType": "sedan",
        "pickupLocation": "Ottawa",
        "pickupDate": "2026-04-01",
        "returnDate": "2026-04-05",
        "notes": "GPS, child seat"
    }
    """
    logging.info("check-booking function triggered")

    try:
        booking = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON in request body"}),
            mimetype="application/json",
            status_code=400
        )

    # Validate required fields
    required_fields = ["bookingId", "customerName", "customerEmail", "vehicleType", "pickupLocation"]
    missing = [f for f in required_fields if f not in booking]
    if missing:
        return func.HttpResponse(
            json.dumps({"error": f"Missing required fields: {', '.join(missing)}"}),
            mimetype="application/json",
            status_code=400
        )

    booking_id = booking["bookingId"]
    vehicle_type = booking["vehicleType"].lower()
    pickup_location = booking["pickupLocation"]

    logging.info(f"Evaluating {booking_id}: {vehicle_type} in {pickup_location}")

    # Search fleet for matching available vehicles
    matching = [
        v for v in FLEET
        if v["type"].lower() == vehicle_type
        and v["location"].lower() == pickup_location.lower()
        and v["available"]
    ]

    if matching:
        # Assign the vehicle with the lowest mileage (best condition)
        vehicle = min(matching, key=lambda v: v["mileage"])

        # Calculate pricing
        pricing = calculate_price(
            vehicle["dailyRate"],
            booking.get("pickupDate"),
            booking.get("returnDate"),
            booking.get("notes", "")
        )

        result = {
            "bookingId": booking_id,
            "customerName": booking["customerName"],
            "customerEmail": booking["customerEmail"],
            "status": "confirmed",
            "vehicleId": vehicle["id"],
            "vehicleType": vehicle["type"],
            "location": vehicle["location"],
            "pickupDate": booking.get("pickupDate", "TBD"),
            "returnDate": booking.get("returnDate", "TBD"),
            "pricing": pricing,
            "estimatedPrice": pricing["estimatedPrice"],
            "reason": f"Vehicle {vehicle['id']} ({vehicle['type']}) available in {vehicle['location']} — {vehicle['mileage']} km, ${vehicle['dailyRate']}/day"
        }
        logging.info(f"{booking_id} CONFIRMED — {vehicle['id']}, ${pricing['estimatedPrice']}")
    else:
        # Determine specific rejection reason
        type_matches = [v for v in FLEET if v["type"].lower() == vehicle_type]
        location_matches = [v for v in type_matches if v["location"].lower() == pickup_location.lower()]

        if not type_matches:
            reason = f"No {vehicle_type} vehicles in the fleet"
        elif not location_matches:
            available_locations = list(set(v["location"] for v in type_matches if v["available"]))
            if available_locations:
                reason = f"No {vehicle_type} available in {pickup_location}. Try: {', '.join(sorted(available_locations))}"
            else:
                reason = f"All {vehicle_type} vehicles are currently booked across all locations"
        else:
            reason = f"All {vehicle_type} vehicles in {pickup_location} are currently booked"

        result = {
            "bookingId": booking_id,
            "customerName": booking["customerName"],
            "customerEmail": booking["customerEmail"],
            "status": "rejected",
            "vehicleId": None,
            "vehicleType": vehicle_type,
            "location": pickup_location,
            "pickupDate": booking.get("pickupDate", "TBD"),
            "returnDate": booking.get("returnDate", "TBD"),
            "estimatedPrice": None,
            "reason": reason
        }
        logging.info(f"{booking_id} REJECTED — {reason}")

    return func.HttpResponse(
        json.dumps(result),
        mimetype="application/json",
        status_code=200
    )


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.function_name(name="health")
@app.route(route="", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint."""
    return func.HttpResponse(
        json.dumps({"status": "healthy", "service": "FleetBook Function App", "fleet_size": len(FLEET)}),
        mimetype="application/json",
        status_code=200
    )