from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics.models import DailyAnalytics, ImpactMetrics, SystemMetrics
from transactions.models import Rating, Transaction


class Command(BaseCommand):
    help = "Recalculates analytics metrics for a date range"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=180,
            help="Number of days to recalculate metrics for (default: 180)",
        )
        parser.add_argument(
            "--metrics",
            type=str,
            default="all",
            choices=["all", "impact", "system"],
            help="Type of metrics to recalculate (default: all)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recalculation even if metrics exist",
        )

    def handle(self, *args, **options):
        days = options["days"]
        metrics_type = options["metrics"]
        force = options["force"]
        
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days - 1)

        self.stdout.write(f"Recalculating metrics from {start_date} to {end_date}...")
        
        # Get list of completed transactions in date range for validation
        completed_txns = Transaction.objects.filter(
            status="COMPLETED",
            completion_date__date__gte=start_date, 
            completion_date__date__lte=end_date
        ).count()
        
        self.stdout.write(f"Found {completed_txns} completed transactions in date range")

        # Calculate metrics for each date in the range
        current_date = start_date
        impact_count = 0
        system_count = 0
        
        while current_date <= end_date:
            try:
                # Calculate impact metrics if requested
                if metrics_type in ["all", "impact"]:
                    # Check if metrics exist for this date and respect force flag
                    metrics_exist = ImpactMetrics.objects.filter(date=current_date).exists()
                    if force or not metrics_exist:
                        impact_metrics = ImpactMetrics.calculate_for_date(current_date)
                        self.stdout.write(
                            f"Impact metrics for {current_date}: {impact_metrics.food_redistributed_kg}kg food redistributed, "
                            f"{impact_metrics.co2_emissions_saved}kg CO2 saved, {impact_metrics.meals_provided} meals provided"
                        )
                        impact_count += 1
                    else:
                        self.stdout.write(f"Skipping existing impact metrics for {current_date} (use --force to override)")

                # Calculate system metrics if requested
                if metrics_type in ["all", "system"]:
                    # Check if metrics exist for this date and respect force flag
                    metrics_exist = SystemMetrics.objects.filter(date=current_date).exists()
                    if force or not metrics_exist:
                        system_metrics = SystemMetrics.calculate_for_date(current_date)
                        self.stdout.write(
                            f"System metrics for {current_date}: {system_metrics.active_users} active users, "
                            f"{system_metrics.transaction_completion_rate}% completion rate"
                        )
                        system_count += 1
                    else:
                        self.stdout.write(f"Skipping existing system metrics for {current_date} (use --force to override)")
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error calculating metrics for {current_date}: {str(e)}")
                )

            current_date += timedelta(days=1)

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully recalculated {impact_count} impact metrics and {system_count} system metrics"
            )
        )
