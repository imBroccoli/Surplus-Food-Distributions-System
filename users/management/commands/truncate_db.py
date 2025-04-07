from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone
import os
import shutil


class Command(BaseCommand):
    help = "Truncates all tables in the database with safety measures"

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompt',
        )
        parser.add_argument(
            '--backup',
            action='store_true',
            help='Create a backup before truncating',
            default=True,
        )

    def handle(self, *args, **options):
        if not options['force']:
            confirm = input('This will delete ALL data. Are you sure? [y/N]: ')
            if confirm.lower() != 'y':
                self.stdout.write('Operation cancelled.')
                return

        # Create backup if requested
        if options['backup']:
            try:
                self._create_backup()
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Failed to create backup: {str(e)}')
                )
                return

        self.stdout.write('Truncating all tables...')

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Get database engine being used
                    db_engine = connection.vendor

                    # Disable foreign key checks based on database
                    if db_engine == 'mysql':
                        cursor.execute('SET FOREIGN_KEY_CHECKS = 0;')
                    elif db_engine == 'postgresql':
                        cursor.execute('SET CONSTRAINTS ALL DEFERRED;')
                    elif db_engine == 'sqlite3':
                        cursor.execute('PRAGMA foreign_keys = OFF;')

                    # Get all models and sort them to handle dependencies
                    models = apps.get_models()
                    
                    for model in models:
                        table_name = model._meta.db_table
                        self.stdout.write(f'Truncating table: {table_name}')
                        
                        try:
                            # Use database-specific truncate syntax
                            if db_engine in ['postgresql', 'mysql']:
                                cursor.execute(f'TRUNCATE TABLE "{table_name}" CASCADE;')
                            elif db_engine == 'sqlite3':
                                cursor.execute(f'DELETE FROM "{table_name}";')
                                cursor.execute(f'DELETE FROM sqlite_sequence WHERE name="{table_name}";')
                            
                        except (OperationalError, ProgrammingError) as e:
                            self.stdout.write(
                                self.style.WARNING(f'Error truncating {table_name}: {str(e)}')
                            )

                    # Re-enable foreign key checks
                    if db_engine == 'mysql':
                        cursor.execute('SET FOREIGN_KEY_CHECKS = 1;')
                    elif db_engine == 'postgresql':
                        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE;')
                    elif db_engine == 'sqlite3':
                        cursor.execute('PRAGMA foreign_keys = ON;')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to truncate tables: {str(e)}')
            )
            return

        self.stdout.write(self.style.SUCCESS('Successfully truncated all tables'))

    def _create_backup(self):
        """Create a backup of the database before truncating"""
        if connection.vendor == 'sqlite3':
            db_path = connection.settings_dict['NAME']
            backup_path = f"{db_path}.backup-{timezone.now().strftime('%Y%m%d_%H%M%S')}"
            
            if os.path.exists(db_path):
                shutil.copy2(db_path, backup_path)
                self.stdout.write(
                    self.style.SUCCESS(f'Created backup at {backup_path}')
                )
        else:
            self.stdout.write(
                self.style.WARNING('Automatic backup is only supported for SQLite databases')
            )
