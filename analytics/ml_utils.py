import os
import joblib
import numpy as np
import pandas as pd
from django.conf import settings

# Define path to the model file
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_models')
MODEL_PATH = os.path.join(MODEL_DIR, 'listing_expiry_model.pkl')

# Ensure the model directory exists
os.makedirs(MODEL_DIR, exist_ok=True)

# Singleton to hold the loaded model
_model = None

def get_model():
    """Load the model as a singleton to avoid reloading it on each prediction."""
    global _model
    if _model is None:
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
        else:
            # Return None if model doesn't exist yet
            return None
    return _model

def predict_expiry_risk(quantity, time_to_expiry, listing_type="COMMERCIAL", has_min_quantity=False):
    """
    Predict the probability that a food listing will expire before being claimed.
    
    Args:
        quantity: The quantity of food in the listing
        time_to_expiry: Time until expiry in days
        listing_type: The type of listing (COMMERCIAL, DONATION, NONPROFIT_ONLY)
        has_min_quantity: Whether the listing has a minimum quantity requirement
        
    Returns:
        Float between 0 and 1 representing the probability of expiry
    """
    model = get_model()
    
    if model is None:
        # If model doesn't exist, use a simple heuristic
        # Higher risk for shorter expiry times and commercial listings
        base_risk = max(0, min(1, 1 - (time_to_expiry / 14)))  # Base risk from time to expiry (2 weeks scale)
        if listing_type == "COMMERCIAL":
            type_factor = 0.7  # Commercial listings expire more often
        elif listing_type == "NONPROFIT_ONLY":
            type_factor = 0.4  # Nonprofit-only listings have lower risk
        else:
            type_factor = 0.5  # Default for other types (e.g., DONATION)
        quantity_factor = min(1, quantity / 100)  # Larger quantities may be harder to claim
        
        # Combine factors with weightings
        risk = (base_risk * 0.6) + (type_factor * 0.3) + (quantity_factor * 0.1)
        return min(1, max(0, risk))  # Ensure the result is between 0 and 1
    
    # Create features expected by the model
    # Only treat 'DONATION' as a donation; 'NONPROFIT_ONLY' is not a donation in this business logic
    is_donation = listing_type == "DONATION"
    # Use DataFrame to match feature names and avoid sklearn warning
    X = pd.DataFrame(
        [[quantity, time_to_expiry, is_donation, has_min_quantity]],
        columns=["quantity", "time_to_expiry", "is_donation", "has_min_quantity"]
    )
    # Defensive: handle single-class model (avoid IndexError)
    proba = model.predict_proba(X)
    if proba.shape[1] == 2:
        return proba[0][1]
    else:
        # Only one class present in training, return 0.0 or 1.0 depending on the class
        if hasattr(model, 'classes_'):
            if model.classes_[0] == 0:
                return 0.0
            else:
                return 1.0
        return float(proba[0][0])

def train_expiry_model(csv_path="listing_data.csv"):
    """
    Train a model to predict food listing expiry risk.
    
    Args:
        csv_path: Path to the CSV file with listing data
        
    Returns:
        True if training was successful, False otherwise
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    
    try:
        # Load data
        df = pd.read_csv(csv_path)
        
        # Skip if we don't have enough data
        if len(df) < 20:
            return False
        
        # Select features
        X = df[["quantity", "time_to_expiry", "is_donation", "has_min_quantity"]]
        y = df["expired"].astype(int)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Train model
        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X_train, y_train)
        
        # Evaluate
        y_pred = clf.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        
        print("Model evaluation results:")
        print(f"Accuracy: {accuracy:.4f}")
        print(f"Precision: {precision:.4f}")
        print(f"Recall: {recall:.4f}")
        print(f"F1 Score: {f1:.4f}")
        
        # Save model
        joblib.dump(clf, MODEL_PATH)
        return True
        
    except Exception as e:
        print(f"Error training model: {str(e)}")
        return False