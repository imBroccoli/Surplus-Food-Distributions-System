# Surplus Food Distribution Platform

This project is a Django-based web application for managing surplus food listings, analytics, and expiry risk prediction using machine learning. It features automated data export and model training using Celery and Redis, and is designed to run on Windows (with WSL for Redis support).

---

## Table of Contents
- [Features](#features)
- [System Requirements](#system-requirements)
- [Initial Setup](#initial-setup)
- [WSL and Redis Setup](#wsl-and-redis-setup)
- [Python Environment & Dependencies](#python-environment--dependencies)
- [Database Setup](#database-setup)
- [Running the Project](#running-the-project)
- [Celery & Task Automation](#celery--task-automation)
- [Project Management Commands](#project-management-commands)
- [Troubleshooting](#troubleshooting)

---

## Features
- Food listing management for businesses and nonprofits
- Expiry risk prediction using a machine learning model
- Automated export of listing data and model retraining (via Celery)
- Analytics dashboards and reporting
- Notification system for suppliers

---

## System Requirements
- **Windows 10/11** (Home or Pro)
- **WSL (Windows Subsystem for Linux)** (for Redis)
- **Python 3.12+** (recommended)
- **PostgreSQL** (or your configured database)
- **Redis** (running in WSL)

---

## Initial Setup

### 1. Enable WSL (Windows Subsystem for Linux)
- Open PowerShell as Administrator and run:
  ```sh
  wsl --install
  ```
- Restart your computer if prompted.
- Install a Linux distribution (e.g., Ubuntu) from the Microsoft Store.
- Launch Ubuntu from the Start menu and complete the initial setup.

### 2. Install Redis on WSL
- Open your WSL terminal (e.g., Ubuntu) and run:
  ```sh
  sudo apt update
  sudo apt install redis-server
  sudo service redis-server start
  ```
- To check if Redis is running:
  ```sh
  redis-cli ping
  ```
  You should see `PONG`.
- Redis will now be available at `localhost:6379` for your Windows apps.

---

## Python Environment & Dependencies

### 1. Install Python (if not already installed)
- Download and install Python 3.12+ from [python.org](https://www.python.org/downloads/).
- Add Python to your PATH during installation.

### 2. Create and Activate a Virtual Environment
```sh
python -m venv venv
venv\Scripts\activate  # On Windows
# or
source venv/bin/activate  # On WSL/Linux
```

### 3. Install Project Dependencies
```sh
pip install -r requirements.txt
```

---

## Database Setup
- Ensure PostgreSQL is installed and running.
- Create a database and user matching your `config/settings.py`.
- Apply migrations:
  ```sh
  python manage.py migrate
  ```
- (Optional) Populate with dummy data:
  ```sh
  python manage.py populate_dummy_data
  ```

---

## Running the Project

### 1. Start the Django Development Server
```sh
python manage.py runserver
```
- Visit [http://localhost:8000](http://localhost:8000) in your browser.

### 2. Start Celery Worker and Beat (for automation)
Open two terminals:
```sh
celery -A config worker --pool=solo -l info
celery -A config beat -l info
```
- The worker processes tasks; beat schedules them (e.g., hourly export and training).
- Make sure Redis is running in WSL before starting Celery.

---

## Celery & Task Automation
- **Automated Export & Training:**
  - The system will automatically export listing data and retrain the expiry model at the interval set in `config/settings.py` (default: every hour).
  - You can change the interval by editing the `CELERY_BEAT_SCHEDULE` in `settings.py`.
- **Manual Trigger:**
  - You can also manually trigger the task from the Django shell:
    ```python
    from analytics.tasks import export_and_train_expiry_model
    export_and_train_expiry_model.delay()
    ```

---

## Project Management Commands

| Command | Description |
|---------|-------------|
| `python manage.py migrate` | Apply database migrations |
| `python manage.py populate_dummy_data` | Populate DB with sample data |
| `python manage.py export_listing_data` | Export food listing data to CSV for ML |
| `python manage.py train_expiry_model` | Train the expiry risk ML model |
| `python manage.py recalculate_metrics --days 30` | Recalculate analytics metrics |
| `python manage.py backfill_analytics` | Populate missing analytics from transactions |
| `python manage.py truncate_db` | Truncate all tables (dangerous!) |

---

## Troubleshooting

- **Redis connection errors:**
  - Make sure Redis is running in WSL (`sudo service redis-server start`).
  - If you see `Connection refused`, check your firewall and that Redis is listening on `localhost`.
- **Celery worker not processing tasks:**
  - Ensure both the worker and beat are running.
  - Check the terminal for errors.
- **Model not predicting risk:**
  - Ensure your `listing_data.csv` contains both expired and non-expired listings.
  - Retrain the model if you update the data.
- **Windows-specific issues:**
  - Always use `--pool=solo` with Celery on Windows.
  - If you have WSL2, you can also run Redis in Docker if preferred.

---

## Additional Notes
- For production, consider using a process manager (like Supervisor) to keep Celery and Redis running.
- You can monitor Celery tasks with [Flower](https://flower.readthedocs.io/en/latest/) or [django-celery-results](https://django-celery-results.readthedocs.io/en/latest/).
- For more commands, see `commands.md` in the project root.

---

**Enjoy using the Surplus Food Distribution Platform!**
