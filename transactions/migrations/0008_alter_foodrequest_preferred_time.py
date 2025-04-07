# Generated by Django 5.1.6 on 2025-03-26 17:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0007_remove_foodrequest_preferred_window_end_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='foodrequest',
            name='preferred_time',
            field=models.CharField(choices=[('morning', 'Morning: 8:00 AM - 11:00 AM'), ('afternoon', 'Afternoon: 12:00 PM - 4:00 PM'), ('evening', 'Evening: 5:00 PM - 8:00 PM'), ('night', 'Night: 9:00 PM - 11:00 PM')], max_length=20, null=True),
        ),
    ]
