### For truncate the DB
python manage.py truncate_db

### For pouplating the DB with dummy Data
python manage.py populate_dummy_data


### For recalculating metrics - Use to recalculate historical data or fix any discrepancies
python manage.py recalculate_metrics --days 30

### Used to populate missing data from existing transactions
python manage.py backfill_analytics