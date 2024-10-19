import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
import datetime

load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

firebase_creds = {
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY"),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL"),
}

cred = credentials.Certificate(firebase_creds)



firebase_admin.initialize_app((cred), {
    'databaseURL': 'https://sparkathon-ee76f-default-rtdb.firebaseio.com/'  # Replace with your database URL
})

# Function to get storage data from Firebase
def get_storage_data():
    ref = db.reference('storages')
    return ref.get()

# Function to update item quantity in storage
def update_item(storage_id, item_name, amount, add=True):
    ref = db.reference(f'storages/{storage_id}/items/{item_name}')
    item_data = ref.get()

    if item_data:
        current_quantity = item_data.get('present', 0)
        new_quantity = current_quantity + amount if add else current_quantity - amount
        ref.update({'present': new_quantity})

# Add item to storage
def add_item(item_name, amount):
    storages = get_storage_data()
    best_storage = None
    worst_size = float('inf')

    for storage_id, storage_data in storages.items():
        size = storage_data.get('size', 0)
        if size < worst_size:
            worst_size = size
            best_storage = storage_id

    if best_storage:
        update_item(best_storage, item_name, amount, add=True)
        return f"Added {amount} of {item_name} to {best_storage}"
    else:
        return "No suitable storage found for adding the item."

# Remove item from storage
def remove_item(item_name, amount):
    storages = get_storage_data()
    best_storage = None
    best_size = -1

    for storage_id, storage_data in storages.items():
        size = storage_data.get('size', 0)
        item_data = storage_data.get('items', {}).get(item_name, {})
        present = item_data.get('present', 0)

        if size > best_size and present >= amount:
            best_size = size
            best_storage = storage_id

    if best_storage:
        update_item(best_storage, item_name, amount, add=False)
        return f"Removed {amount} of {item_name} from {best_storage}"
    else:
        return "No suitable storage found for removing the item."

# Route to process the item operation (Add/Remove)
@app.route('/process_item', methods=['POST'])
def process_item():
    data = request.get_json()
    item_name = data.get('item_name', '')
    amount = data.get('amount', 0)
    operation = data.get('operation', '')

    if operation == 'Add':
        result = add_item(item_name, amount)
    elif operation == 'Remove':
        result = remove_item(item_name, amount)
    else:
        result = 'Invalid operation'

    return jsonify({'result': result})

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    item_name = data.get('item', '')
    storage_name = data.get('storage', '')

    # Get sales data from Firebase
    ref = db.reference(f'storages/{storage_name}/items/{item_name}')
    item_data = ref.get()

    if not item_data:
        return jsonify({"error": "Item not found"}), 404

    dates = []
    sales_data = []

    # Retrieve only date and sales values
    for date_str, sales in item_data.items():
        # Check if the key is a valid date and sales value is an integer
        try:
            if date_str != 'present' and isinstance(sales, int):
                # Try to parse the date string
                date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
                dates.append(date)
                sales_data.append(sales)
        except ValueError:
            # Ignore keys that do not match the date format
            continue

    if not dates:
        return jsonify({"error": "No sales data found for the item"}), 404

    # Convert to pandas series
    sales_series = pd.Series(sales_data, index=dates)

    # Forecasting future sales using Exponential Smoothing
    model = ExponentialSmoothing(sales_series, seasonal='add', seasonal_periods=7)
    fit = model.fit()
    forecast = fit.forecast(steps=30)
    predicted_sales = forecast.cumsum()

    current_inventory = item_data['present']
    end_date = None

    # Predict when inventory will run out
    for day, sales in enumerate(predicted_sales):
        if sales >= current_inventory:
            end_date = dates[-1] + pd.Timedelta(days=day)
            break

    if end_date:
        forecast_dates = [dates[-1] + pd.Timedelta(days=i) for i in range(1, 31)]
        return jsonify({
            "values": list(predicted_sales),
            "date": end_date.date().strftime("%Y-%m-%d"),
            "forecast_dates": [date.strftime("%Y-%m-%d") for date in forecast_dates]
        })
    else:
        return jsonify({
            "values": list(predicted_sales),
            "forecast_dates": [],
            "date": "Not expected to run out in the next 30 days"
        })

# Start the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
