# Lab 3: FleetBook Vehicle Booking with Service Bus, Logic Apps & Functions

## Demo Video

[Youtube Link](https://youtu.be/-sRg2U8a-AY)

## Services

| Service                                               | Role                                                |
| ----------------------------------------------------- | --------------------------------------------------- |
| Service Bus Queue (`booking-queue`)                   | Buffers incoming booking requests                   |
| Logic App (`process-booking`)                         | Orchestrates the full workflow                      |
| Azure Function (`check-booking`)                      | Evaluates fleet availability and calculates pricing |
| Service Bus Topic (`booking-results`)                 | Publishes decisions for downstream consumers        |
| Topic Subscriptions (`confirmed-sub`, `rejected-sub`) | Filter messages by label                            |
| Outlook.com Connector                                 | Sends emails to customers                           |
| Web Client (`client.html`)                            | FleetBook booking interface                         |

---

## Part 1: Service Bus

### 1.1 Create a Resource Group
- Name: `rg-serverless-lab3` | Region: Canada Central

### 1.2 Create a Service Bus Namespace
- Pricing tier: **Standard** (required for topics)
- Save the Primary Connection String and Primary Key from Shared access policies > RootManageSharedAccessKey

### 1.3 Create the Booking Queue
- Name: `booking-queue` | Leave defaults

### 1.4 Create the Booking Results Topic
- Name: `booking-results` | Leave defaults

### 1.5 Create Filtered Subscriptions

**confirmed-sub**
- Subscription name: `confirmed-sub` | Max delivery count: 10
- Filter: SQL Filter | Expression: `sys.label = 'confirmed'`

**rejected-sub**
- Subscription name: `rejected-sub` | Max delivery count: 10
- Filter: SQL Filter | Expression: `sys.label = 'rejected'`

---

## Part 2: Azure Function

### 2.1 Create and Configure the Project

Create a new Azure Functions project (Python 3.11/3.12) using the `function_app.py` from the provided repo.

`requirements.txt`:
```
azure-functions
```

`local.settings.json`:
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python"
  },
  "Host": { "CORS": "*" }
}
```

The function exposes two endpoints:
- `check-booking` — evaluates fleet availability and calculates pricing
- `health` — deployment verification

---

## Part 3: Logic App

### 3.1 Create the Resource
- Name: `process-booking` | Plan type: Consumption | Same region as Service Bus
- Open the designer and select **Blank Logic App**

### 3.2 Trigger: Service Bus Queue

Search "Service Bus" > select **When a message is received in a queue (auto-complete)**

- Connection string: paste from Part 1
- Queue name: `booking-queue` | Check every: 30 seconds

### 3.3 Decode the Message

Add a **Compose** action. In the Inputs field, use the expression:
```
base64ToString(triggerBody()?['ContentData'])
```
Rename: `Decode Message`

### 3.4 Parse the Booking JSON

Add **Parse JSON**. Content: output of Decode Message. Generate schema from this sample:
```json
{
    "bookingId": "BK-0001",
    "customerName": "Jane Doe",
    "customerEmail": "jane@example.com",
    "vehicleType": "sedan",
    "pickupLocation": "Ottawa",
    "pickupDate": "2026-04-01",
    "returnDate": "2026-04-05",
    "notes": "GPS",
    "submittedAt": "2026-03-25T10:30:00.000Z"
}
```
Rename: `Parse Booking Request`

### 3.5 Call the Azure Function

Add **Azure Functions** > select your function app > select `check-booking`.

- Request Body: `Body` from Parse Booking Request

Rename: `Call Check-Booking Function`

### 3.6 Parse the Function Response

Add **Parse JSON**. Content: `Body` from Call Check-Booking Function. Generate schema from this sample:
```json
{
    "bookingId": "BK-0001",
    "customerName": "Jane Doe",
    "customerEmail": "jane@example.com",
    "status": "confirmed",
    "vehicleId": "V001",
    "vehicleType": "sedan",
    "location": "Ottawa",
    "pickupDate": "2026-04-01",
    "returnDate": "2026-04-05",
    "estimatedPrice": 200,
    "pricing": {
        "days": 4, "dailyRate": 45, "basePrice": 180,
        "addOns": ["GPS ($5/day)"], "addOnTotal": 20,
        "discount": 0, "estimatedPrice": 200
    },
    "reason": "Vehicle V001 (sedan) available in Ottawa"
}
```

Then manually edit the schema to allow null on two fields (rejected bookings return null for these):
```json
"vehicleId": { "type": ["string", "null"] }
"estimatedPrice": { "type": ["integer", "null"] }
```
Rename: `Parse Function Response`

### 3.7 Condition

Add a **Condition** action:
- Left: `status` from Parse Function Response
- Operator: is equal to
- Right: `confirmed`

### 3.8 TRUE Branch (Confirmed)

**Send Confirmation Email** (Outlook.com > Send an email V2):

| Field   | Value                                                                        |
| ------- | ---------------------------------------------------------------------------- |
| To      | `@{body('Parse_Function_Response')?['customerEmail']}`                       |
| Subject | `FleetBook Confirmation -- @{body('Parse_Function_Response')?['bookingId']}` |

Body:
```
Your booking has been confirmed!

Booking ID: @{body('Parse_Function_Response')?['bookingId']}
Customer: @{body('Parse_Function_Response')?['customerName']}
Vehicle: @{body('Parse_Function_Response')?['vehicleId']} @{body('Parse_Function_Response')?['vehicleType']}
Location: @{body('Parse_Function_Response')?['location']}
Dates: @{body('Parse_Function_Response')?['pickupDate']} to @{body('Parse_Function_Response')?['returnDate']}
Estimated Total: @{body('Parse_Function_Response')?['estimatedPrice']}
Reason: @{body('Parse_Function_Response')?['reason']}

Thank you for choosing FleetBook!
```

**Publish Confirmed to Topic** (Service Bus > Send message):

| Field            | Value                                 |
| ---------------- | ------------------------------------- |
| Queue/Topic name | `booking-results`                     |
| Content          | Body from Call Check-Booking Function |
| Label            | `confirmed`                           |
| Content Type     | `application/json`                    |

### 3.9 FALSE Branch (Rejected)

**Send Rejection Email** (same connector):

| Field   | Value                                                                                          |
| ------- | ---------------------------------------------------------------------------------------------- |
| To      | `@{body('Parse_Function_Response')?['customerEmail']}`                                         |
| Subject | `FleetBook -- Booking @{body('Parse_Function_Response')?['bookingId']} Could Not Be Confirmed` |

Body:
```
We're sorry, your booking could not be confirmed.

Booking ID: @{body('Parse_Function_Response')?['bookingId']}
Customer: @{body('Parse_Function_Response')?['customerName']}
Requested: @{body('Parse_Function_Response')?['vehicleType']} in @{body('Parse_Function_Response')?['location']}
Dates: @{body('Parse_Function_Response')?['pickupDate']} to @{body('Parse_Function_Response')?['returnDate']}
Reason: @{body('Parse_Function_Response')?['reason']}

Please try a different vehicle type or location.
```

**Publish Rejected to Topic** (same as confirmed step, but Label: `rejected`)

Save the Logic App.

---

## Part 4: Web Client

Copy `client.html` from the provided repo. Open it in a browser and configure:

- **Namespace Name:** your Service Bus namespace (e.g., `yourname-booking-sb`)
- **SAS Key:** Primary Key from Shared access policies (not the full connection string)

The client sends bookings to the queue via the Service Bus REST API, then polls `confirmed-sub` and `rejected-sub` every 5 seconds to display results.
