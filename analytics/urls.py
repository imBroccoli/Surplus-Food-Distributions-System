from django.urls import path
from . import views

app_name = "analytics"

urlpatterns = [
    # Report Generation and Management
    path("reports/all/", views.all_reports, name="all_reports"),
    path("reports/bulk-delete/", views.bulk_delete_reports, name="bulk_delete_reports"),
    path("reports/generate/", views.generate_report, name="generate_report"),
    path(
        "reports/<int:report_id>/regenerate/",
        views.regenerate_report,
        name="regenerate_report",
    ),
    path(
        "reports/<int:report_id>/schedule/",
        views.schedule_report,
        name="schedule_report",
    ),
    path(
        "reports/<int:report_id>/unschedule/",
        views.unschedule_report,
        name="unschedule_report",
    ),
    path("reports/<int:report_id>/delete/", views.delete_report, name="delete_report"),
    path("reports/<int:report_id>/update/", views.update_report, name="update_report"),
    path(
        "reports/<int:report_id>/export/<str:export_format>/",
        views.export_report,
        name="export_report",
    ),
    path("reports/<int:report_id>/", views.report_detail, name="report_detail"),
    path("reports/<str:report_type>/", views.report_list, name="report_list"),
    path("reports/", views.reports_dashboard, name="reports_dashboard"),
    # Analytics Dashboards
    path("", views.analytics_dashboard, name="dashboard"),
    path("impact/", views.impact_dashboard, name="impact_dashboard"),
    path("system/", views.system_analytics, name="system_analytics"),
    path("activity/", views.user_activity, name="user_activity"),
    path("activity/admin/", views.admin_activity, name="admin_activity"),
    path("business/", views.business_analytics, name="business_analytics"),
    path(
        "business/data/", views.business_analytics_data, name="business_analytics_data"
    ),
    path(
        "business/export/<str:export_format>/",
        views.business_export,
        name="business_export",
    ),
    path("admin/", views.admin_analytics_dashboard, name="admin_analytics"),
]
