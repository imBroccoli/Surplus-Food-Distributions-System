# Generated by Django 5.1.6 on 2025-03-05 15:52

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('food_listings', '0003_foodlisting_food_listin_listing_abcd91_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ImpactMetrics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('food_redistributed_kg', models.DecimalField(decimal_places=2, default=0, help_text='Total weight of food redistributed in kilograms', max_digits=10)),
                ('co2_emissions_saved', models.DecimalField(decimal_places=2, default=0, help_text='Estimated CO2 emissions saved in kilograms', max_digits=10)),
                ('meals_provided', models.IntegerField(default=0, help_text='Estimated number of meals provided')),
                ('monetary_value_saved', models.DecimalField(decimal_places=2, default=0, help_text='Estimated monetary value saved in dollars', max_digits=10)),
            ],
            options={
                'verbose_name': 'Impact Metrics',
                'verbose_name_plural': 'Impact Metrics',
                'ordering': ['-date'],
                'indexes': [models.Index(fields=['date'], name='analytics_i_date_ce3557_idx')],
            },
        ),
        migrations.CreateModel(
            name='DailyAnalytics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('requests_received', models.IntegerField(default=0)),
                ('requests_fulfilled', models.IntegerField(default=0)),
                ('food_saved_kg', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='food_listings.foodlisting')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Daily Analytics',
                'verbose_name_plural': 'Daily Analytics',
                'ordering': ['-date'],
                'indexes': [models.Index(fields=['date', 'user'], name='analytics_d_date_21804f_idx'), models.Index(fields=['date', 'listing'], name='analytics_d_date_3c1516_idx')],
            },
        ),
    ]
