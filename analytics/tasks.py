from celery import shared_task
import os

@shared_task
def export_and_train_expiry_model():
    os.system('python manage.py export_listing_data')
    os.system('python manage.py train_expiry_model')
