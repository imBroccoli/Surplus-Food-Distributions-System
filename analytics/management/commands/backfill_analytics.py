from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone
from django.db.models import Sum, Count, Case, When, F, Q, DecimalField

from analytics.models import DailyAnalytics, ImpactMetrics, SystemMetrics
from transactions.models import FoodRequest, Transaction
from food_listings.models import FoodListing
from users.models import CustomUser


class Command(BaseCommand):
    help = "Backfills analytics data from existing transactions"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing analytics before backfilling',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Number of days to backfill from today (default: all historical data)',
        )
        parser.add_argument(
            '--metrics',
            type=str,
            default='all',
            choices=['all', 'daily', 'impact', 'system', 'business'],
            help='Type of metrics to backfill (default: all)',
        )
        parser.add_argument(
            '--business-id',
            type=int,
            default=None,
            help='Specific business user ID to backfill data for (only when --metrics=business)',
        )

    def handle(self, *args, **options):
        self.stdout.write("Starting analytics backfill...")
        should_clear = options.get('clear', False)
        days = options.get('days', None)
        metrics_type = options.get('metrics', 'all')
        business_id = options.get('business_id')
        
        # Define the date range for backfilling
        today = timezone.now().date()
        start_date = None
        
        if days:
            start_date = today - timedelta(days=days)
            self.stdout.write(f"Backfilling data from {start_date} to {today}")
        else:
            self.stdout.write(f"Backfilling all historical data")

        # Clear existing data if requested
        if should_clear:
            self.clear_existing_data(metrics_type)

        # Process data based on metrics type
        if metrics_type in ['all', 'daily']:
            self.backfill_daily_analytics(start_date)
            
        if metrics_type in ['all', 'impact']:
            self.backfill_impact_metrics(start_date)
            
        if metrics_type in ['all', 'system']:
            self.backfill_system_metrics(start_date)
            
        if metrics_type in ['all', 'business'] or business_id:
            self.backfill_business_analytics(start_date, business_id)

    def clear_existing_data(self, metrics_type):
        """Clear existing analytics data based on metrics type"""
        with db_transaction.atomic():
            try:
                if metrics_type in ['all', 'daily', 'business']:
                    self.stdout.write("Clearing existing daily analytics...")
                    DailyAnalytics.objects.all().delete()
                    
                if metrics_type in ['all', 'impact']:
                    self.stdout.write("Clearing existing impact metrics...")
                    ImpactMetrics.objects.all().delete()
                    
                if metrics_type in ['all', 'system']:
                    self.stdout.write("Clearing existing system metrics...")
                    SystemMetrics.objects.all().delete()
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error clearing data: {str(e)}")
                )

    def backfill_daily_analytics(self, start_date):
        """Backfill daily analytics data from transactions"""
        self.stdout.write("Backfilling daily analytics...")
        analytics_data = {}
        
        # Apply date filter if provided
        transaction_query = Transaction.objects.select_related(
            'request',
            'request__listing',
            'request__listing__supplier'
        ).filter(
            status='COMPLETED',
            completion_date__isnull=False
        )
        
        if start_date:
            transaction_query = transaction_query.filter(
                completion_date__date__gte=start_date
            )
        
        # Count transactions to process
        txn_count = transaction_query.count()
        self.stdout.write(f"Found {txn_count} completed transactions to process")

        # Process transactions
        for i, transaction in enumerate(transaction_query, 1):
            if i % 100 == 0:
                self.stdout.write(f"Processing transaction {i} of {txn_count}...")
                
            request = transaction.request
            if not request or not request.listing or not request.listing.supplier:
                continue

            date = transaction.completion_date.date()
            key = (date, request.listing.supplier.id, request.listing.id)

            if key not in analytics_data:
                analytics_data[key] = {
                    'requests_received': 0,
                    'requests_fulfilled': 0,
                    'food_saved_kg': Decimal('0.00'),
                }

            # Count this as both received and fulfilled since it's completed
            analytics_data[key]['requests_received'] += 1
            analytics_data[key]['requests_fulfilled'] += 1
            
            if request.quantity_requested:
                analytics_data[key]['food_saved_kg'] += Decimal(str(request.quantity_requested))

        # Add unfulfilled requests to requests_received count
        pending_query = FoodRequest.objects.select_related(
            'listing',
            'listing__supplier'
        ).exclude(
            transaction__status='COMPLETED'
        )
        
        if start_date:
            pending_query = pending_query.filter(
                created_at__date__gte=start_date
            )
            
        pending_count = pending_query.count()
        self.stdout.write(f"Found {pending_count} pending requests to process")

        for i, request in enumerate(pending_query, 1):
            if i % 100 == 0:
                self.stdout.write(f"Processing pending request {i} of {pending_count}...")
                
            if not request.listing or not request.listing.supplier:
                continue
                
            date = request.created_at.date()
            key = (date, request.listing.supplier.id, request.listing.id)

            if key not in analytics_data:
                analytics_data[key] = {
                    'requests_received': 0,
                    'requests_fulfilled': 0,
                    'food_saved_kg': Decimal('0.00'),
                }
            
            analytics_data[key]['requests_received'] += 1

        # Create DailyAnalytics records
        with db_transaction.atomic():
            try:
                created_count = 0
                updated_count = 0
                
                for (date, supplier_id, listing_id), data in analytics_data.items():
                    analytics, created = DailyAnalytics.objects.update_or_create(
                        date=date,
                        user_id=supplier_id,
                        listing_id=listing_id,
                        defaults={
                            'requests_received': data['requests_received'],
                            'requests_fulfilled': data['requests_fulfilled'],
                            'food_saved_kg': data['food_saved_kg'],
                        }
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                        
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully processed {created_count} new and {updated_count} updated daily analytics records"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error creating daily analytics: {str(e)}")
                )

    def backfill_impact_metrics(self, start_date):
        """Backfill impact metrics for all dates with completed transactions"""
        self.stdout.write("Backfilling impact metrics...")
        try:
            # Get all unique dates from completed transactions
            transaction_query = Transaction.objects.filter(
                status='COMPLETED',
                completion_date__isnull=False
            )
            
            if start_date:
                transaction_query = transaction_query.filter(
                    completion_date__date__gte=start_date
                )
                
            dates = set()
            
            for transaction in transaction_query:
                if transaction.completion_date:
                    dates.add(transaction.completion_date.date())
                    
            self.stdout.write(f"Found {len(dates)} unique dates with transactions")
            
            # Calculate metrics for each date
            created_count = 0
            updated_count = 0
            
            for date in sorted(dates):
                metrics, created = ImpactMetrics.objects.update_or_create(
                    date=date,
                    defaults={}
                )
                
                # Recalculate metrics for the date
                metrics = ImpactMetrics.calculate_for_date(date)
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                    
                self.stdout.write(
                    f"Updated impact metrics for {date}: {metrics.food_redistributed_kg}kg food, "
                    f"{metrics.co2_emissions_saved}kg CO2, {metrics.meals_provided} meals"
                )
                
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully processed {created_count} new and {updated_count} updated impact metrics"
                )
            )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error backfilling impact metrics: {str(e)}")
            )

    def backfill_system_metrics(self, start_date):
        """Backfill system metrics for all dates with activity"""
        self.stdout.write("Backfilling system metrics...")
        try:
            # Get today and determine date range
            today = timezone.now().date()
            
            if start_date is None:
                # Find the earliest transaction date
                earliest_txn = Transaction.objects.order_by('transaction_date').first()
                if earliest_txn and earliest_txn.transaction_date:
                    start_date = earliest_txn.transaction_date.date()
                else:
                    start_date = today - timedelta(days=30)
            
            # Generate all dates in range
            current_date = start_date
            created_count = 0
            updated_count = 0
            
            while current_date <= today:
                try:
                    metrics, created = SystemMetrics.objects.update_or_create(
                        date=current_date,
                        defaults={}
                    )
                    
                    # Recalculate system metrics
                    metrics = SystemMetrics.calculate_for_date(current_date)
                    
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                        
                    self.stdout.write(
                        f"Updated system metrics for {current_date}: {metrics.active_users} active users, "
                        f"{metrics.transaction_completion_rate}% completion rate"
                    )
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f"Error calculating system metrics for {current_date}: {str(e)}")
                    )
                
                # Move to next date
                current_date += timedelta(days=1)
                
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully processed {created_count} new and {updated_count} updated system metrics"
                )
            )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error backfilling system metrics: {str(e)}")
            )
            
    def backfill_business_analytics(self, start_date, business_id=None):
        """Backfill business analytics for business users"""
        self.stdout.write("Backfilling business-specific analytics...")
        try:
            # Determine which business users to process
            business_users = CustomUser.objects.filter(user_type='BUSINESS')
            if business_id:
                business_users = business_users.filter(id=business_id)
                
            # Get today and determine date range
            today = timezone.now().date()
            if start_date is None:
                # Use last 90 days for business data if not specified
                start_date = today - timedelta(days=90)
                
            business_count = business_users.count()
            self.stdout.write(f"Found {business_count} business users to process")
            
            for i, business in enumerate(business_users, 1):
                self.stdout.write(f"Processing business {i} of {business_count}: {business.email}")
                
                # Find all completed transactions involving listings from this business
                business_txns = Transaction.objects.filter(
                    status='COMPLETED',
                    completion_date__date__gte=start_date,
                    completion_date__date__lte=today,
                    request__listing__supplier=business
                )
                
                txn_count = business_txns.count()
                
                # Skip businesses with no transactions in this period
                if txn_count == 0:
                    self.stdout.write(f"No transactions found for {business.email} in the date range")
                    continue
                    
                self.stdout.write(f"Found {txn_count} transactions for {business.email}")
                
                # For each transaction, ensure we have a DailyAnalytics entry
                created = 0
                updated = 0
                
                for txn in business_txns:
                    request = txn.request
                    date = txn.completion_date.date()
                    
                    if request and request.listing:
                        analytics, was_created = DailyAnalytics.objects.update_or_create(
                            date=date,
                            user=business,
                            listing=request.listing,
                            defaults={
                                'requests_received': 1,
                                'requests_fulfilled': 1,
                                'food_saved_kg': Decimal(str(request.quantity_requested or 0))
                            }
                        )
                        
                        if was_created:
                            created += 1
                        else:
                            # If entry already existed but wasn't counting this transaction
                            if analytics.requests_received < 1 or analytics.requests_fulfilled < 1:
                                analytics.requests_received = max(analytics.requests_received, 1)
                                analytics.requests_fulfilled = max(analytics.requests_fulfilled, 1)
                                analytics.food_saved_kg += Decimal(str(request.quantity_requested or 0))
                                analytics.save()
                                
                            updated += 1
                            
                # Add unfulfilled requests 
                pending_requests = FoodRequest.objects.filter(
                    listing__supplier=business
                ).exclude(
                    transaction__status='COMPLETED'
                )
                
                for req in pending_requests:
                    if req.created_at and req.listing:
                        date = req.created_at.date()
                        # Only if within our date range
                        if start_date <= date <= today:
                            analytics, was_created = DailyAnalytics.objects.get_or_create(
                                date=date,
                                user=business,
                                listing=req.listing,
                                defaults={
                                    'requests_received': 1,
                                    'requests_fulfilled': 0,
                                    'food_saved_kg': Decimal('0.00')
                                }
                            )
                            
                            if not was_created:
                                analytics.requests_received += 1
                                analytics.save()
                                
                self.stdout.write(
                    f"Successfully processed business {business.email}: "
                    f"{created} new and {updated} updated analytics entries"
                )
                
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully processed business analytics for {business_count} businesses"
                )
            )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error backfilling business analytics: {str(e)}")
            )
