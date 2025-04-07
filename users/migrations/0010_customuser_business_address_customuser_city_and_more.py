# Generated by Django 5.1.6 on 2025-03-27 11:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0009_remove_customuser_business_address_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='business_address',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='city',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='customuser',
            name='postal_code',
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
