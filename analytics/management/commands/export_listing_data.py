import os
import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from food_listings.models import FoodListing
import pandas as pd

class Command(BaseCommand):
    help = "Export food listing data for machine learning"

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='listing_data.csv',
            help='Output file path'
        )

    def handle(self, *args, **kwargs):
        output_file = kwargs['output']
        
        # Get all food listings including expired ones
        listings = FoodListing.objects.all().values(
            "id", "title", "quantity", "unit", "listing_type", "price",
            "expiry_date", "created_at", "status", "minimum_quantity",
            "requires_verification", "city"
        )
        
        if not listings:
            self.stdout.write(self.style.WARNING("No listings found"))
            return
            
        # Convert to DataFrame
        df = pd.DataFrame(list(listings))
        
        # Create features
        df["time_to_expiry"] = (df["expiry_date"] - df["created_at"]).dt.total_seconds() / 86400  # Convert to days
        df["expired"] = df["status"] == "EXPIRED"
        df["is_donation"] = df["listing_type"] != "COMMERCIAL"
        df["has_price"] = df["price"].notnull()
        df["has_min_quantity"] = df["minimum_quantity"].notnull()
        
        # Export to CSV
        df.to_csv(output_file, index=False)
        self.stdout.write(self.style.SUCCESS(f"Exported {len(df)} food listings to {output_file}"))
        
        # Display feature statistics
        self.stdout.write("\nFeature statistics:")
        self.stdout.write(f"Average time to expiry: {df['time_to_expiry'].mean():.2f} days")
        self.stdout.write(f"Expired listings: {df['expired'].sum()} ({df['expired'].mean()*100:.2f}%)")
        self.stdout.write(f"Donation listings: {df['is_donation'].sum()} ({df['is_donation'].mean()*100:.2f}%)")