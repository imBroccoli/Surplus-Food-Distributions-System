# Generated by Django 5.1.6 on 2025-03-18 12:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0010_remove_impactmetrics_unique_impact_metrics_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='schedule_time',
            field=models.TimeField(blank=True, null=True),
        ),
    ]
