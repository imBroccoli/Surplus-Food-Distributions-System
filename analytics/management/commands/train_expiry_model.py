from django.core.management.base import BaseCommand
from django.core.management import call_command
from analytics.ml_utils import train_expiry_model
import os

class Command(BaseCommand):
    help = "Train the food listing expiry prediction model"

    def add_arguments(self, parser):
        parser.add_argument(
            '--data',
            default='listing_data.csv',
            help='Path to the CSV file with food listing data'
        )
        parser.add_argument(
            '--export',
            action='store_true',
            help='Export data before training'
        )

    def handle(self, *args, **kwargs):
        data_path = kwargs['data']
        export = kwargs['export']
        
        if export or not os.path.exists(data_path):
            self.stdout.write(self.style.NOTICE("Exporting food listing data..."))
            call_command('export_listing_data', output=data_path)
        
        self.stdout.write(self.style.NOTICE("Training food listing expiry prediction model..."))
        success = train_expiry_model(data_path)
        
        if success:
            self.stdout.write(self.style.SUCCESS("Successfully trained the model!"))
        else:
            self.stdout.write(self.style.ERROR("Failed to train the model. Check logs for details."))