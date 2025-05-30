# Generated by Django 5.1.6 on 2025-03-10 16:14

import django.db.models.deletion
import django.utils.timezone
import django_countries.fields
import phonenumber_field.modelfields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('email', models.EmailField(max_length=254, unique=True, verbose_name='email address')),
                ('first_name', models.CharField(max_length=30, verbose_name='first name')),
                ('last_name', models.CharField(max_length=30, verbose_name='last name')),
                ('user_type', models.CharField(choices=[('ADMIN', 'Admin'), ('BUSINESS', 'Business'), ('NONPROFIT', 'Non-Profit'), ('CONSUMER', 'Consumer'), ('VOLUNTEER', 'Volunteer')], default='CONSUMER', max_length=10)),
                ('phone_number', phonenumber_field.modelfields.PhoneNumberField(blank=True, max_length=128, region=None)),
                ('address', models.TextField(blank=True)),
                ('country', django_countries.fields.CountryField(blank=True, max_length=2)),
                ('business_name', models.CharField(blank=True, max_length=255)),
                ('business_type', models.CharField(blank=True, max_length=100)),
                ('business_address', models.TextField(blank=True)),
                ('city', models.CharField(blank=True, max_length=100)),
                ('postal_code', models.CharField(blank=True, max_length=20)),
                ('website', models.URLField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('is_staff', models.BooleanField(default=False)),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now)),
                ('email_verified', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'permissions': [('can_approve_listings', 'Can approve food listings'), ('can_manage_users', 'Can manage user accounts'), ('can_generate_reports', 'Can generate system reports')],
            },
        ),
        migrations.CreateModel(
            name='AdminProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('department', models.CharField(choices=[('GENERAL', 'General Administration'), ('SUPPORT', 'User Support'), ('COMPLIANCE', 'Compliance'), ('ANALYTICS', 'Analytics')], default='GENERAL', max_length=50)),
                ('last_login_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('modules_accessed', models.TextField(blank=True, help_text='Comma-separated list of accessed admin modules')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='admin_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Admin Profile',
                'verbose_name_plural': 'Admin Profiles',
            },
        ),
        migrations.CreateModel(
            name='BusinessProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='business_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Business Profile',
                'verbose_name_plural': 'Business Profiles',
            },
        ),
        migrations.CreateModel(
            name='NonprofitProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization_name', models.CharField(max_length=255)),
                ('registration_number', models.CharField(blank=True, max_length=50, null=True)),
                ('charity_number', models.CharField(blank=True, max_length=50)),
                ('organization_type', models.CharField(choices=[('CHARITY', 'Registered Charity'), ('FOUNDATION', 'Foundation'), ('SOCIAL_ENTERPRISE', 'Social Enterprise'), ('COMMUNITY_GROUP', 'Community Group'), ('OTHER', 'Other')], max_length=50)),
                ('focus_area', models.CharField(blank=True, max_length=100, null=True)),
                ('service_area', models.TextField(blank=True, null=True)),
                ('primary_contact', models.CharField(max_length=255)),
                ('verified_nonprofit', models.BooleanField(default=False)),
                ('rejection_reason', models.TextField(blank=True)),
                ('verification_documents', models.FileField(blank=True, upload_to='nonprofit_verification/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='nonprofit_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Nonprofit Profile',
                'verbose_name_plural': 'Nonprofit Profiles',
            },
        ),
        migrations.CreateModel(
            name='VolunteerProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('availability', models.CharField(choices=[('WEEKDAYS', 'Weekdays'), ('WEEKENDS', 'Weekends'), ('BOTH', 'Both Weekdays and Weekends'), ('FLEXIBLE', 'Flexible')], default='FLEXIBLE', max_length=20)),
                ('transportation_method', models.CharField(choices=[('CAR', 'Personal Car'), ('BIKE', 'Bicycle'), ('PUBLIC', 'Public Transport'), ('WALK', 'Walking'), ('OTHER', 'Other')], max_length=20)),
                ('service_area', models.TextField(help_text='Areas where you can provide delivery service')),
                ('has_valid_license', models.BooleanField(default=False)),
                ('vehicle_type', models.CharField(blank=True, max_length=100)),
                ('max_delivery_weight', models.DecimalField(blank=True, decimal_places=2, help_text='Maximum weight (kg) you can deliver', max_digits=5, null=True)),
                ('completed_deliveries', models.IntegerField(default=0)),
                ('total_impact', models.DecimalField(decimal_places=2, default=0, help_text='Total kg of food delivered', max_digits=10)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='volunteer_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Volunteer Profile',
                'verbose_name_plural': 'Volunteer Profiles',
            },
        ),
    ]
