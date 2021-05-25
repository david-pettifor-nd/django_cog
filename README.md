# Django-Cog
A [django-celery-beat](https://github.com/celery/django-celery-beat) extension to build pipelines of chronological stages and parallel tasks.

## About
Using the Djano admin, this library allows you to create pipelines of multi-staged tasks.  Each pipeline is launched at a specific time, utilizing the `django-celery-beat` `CrontabSchedule` object to define the time of launch.  Once launched, the pipeline looks for the first stage(s) of parallel tasks.  Each task is submitted to a celery worker for completion.  Once all tasks of a stage complete, the stage is considered complete and any proceeding stages will launch (assuming all previous stages required are completed).

### Pipelines
A pipeline is a collection of stages.  It has an optional launch schedule tied to a `CronSchedule` that defines when the pipeline should be launched.  By default, a pipeline will not launch if it detects that a previous launch has not yet completed.

You can also leave the launch schedule blank should you not want a particular pipeline to run on its own.  Instead, clicking the `Launch Now` button on that pipeline's Django admin page will begin its execution.

_Note:_ If a pipeline was previously scheduled using a `CronSchedule` object but needs to be taken off the schedule, simply set the `Schedule` field of the pipeline to the first option of the drop-down menu (`---------`).  This will remove the generated `PeriodicTask` within the database scheduler, preventing further auto-execution of that pipeline.

### Stages
A stage is a collection of tasks that can all be ran independently (and in parallel) of each other.  It can be dependent on any number of previous stages to be complete before launching, but will be launched upon the completion of all prerequisite stages.

If a stage has no prerequisite stages, it will be launched at the start of the Pipeline's launch.  You can have multiple stages run at the same time.

Upon launching a stage, each task that belongs to it will be sent to the `celery` broker for execution.

### Tasks and Cogs

#### Cogs:
A `Cog` is a registered python function that can be used in a task.  To register a function, use the `@cog` function decorator:
```python
from django_cog import cog

@cog
def my_task():
    # do something in a celery worker
    pass
```

**NOTE**: These functions *must* be imported in your application's `__init__.py` file.  Otherwise the auto-discovery process will not find them.

Once Django starts, an auto-discovery process will find all functions with this decorator and create `Cog` records for them in the database.  This allows them to be reference in the Django admin.

#### Tasks:
Once you have cogs registered, you can create a task.  Tasks are specific execution definitions for a cog, and are tied to a stage.  This allows you to run the same function through multiple stages, if needed.

##### Parameters
If your function has parameters needed, you can set these in the Task creation.  See below for an example:

```python
from django_cog import cog

@cog
def add(a, b):
    # add the two numbers together
    return a + b
```

Then in the Task Django admin page, set these variables in the `Arguments as JSON:` field:
```json
{
    "a": 1,
    "b": 2
}
```

## Installation

**IMPORTANT**: It is required that the library is installed and migrations ran PRIOR to registering functions as `cogs`.
First install the library with:

```bash
pip install django-cog
```

Then add it to your Django application's `INSTALLED_APPS` inside your `settings.py` file:
```python
INSTALLED_APPS = [
    ...

    # Django-Cog:
    'django_cog.apps.DjangoCogConfig',

    # Required for nested inline child views in the Django Admin:
    'nested_inline',

    # Optional (recommended):
    'django_celery_beat',
]
```

Lastly, run migrations:
```python
python manage.py migrate django_cog
```

#### Cog Registration
Once migrations complete, it is safe to register your functions using the `cog` decorator:
```python
from django_cog import cog

@cog
def my_task():
    # do something in a celery worker
    pass
```

## Docker-Compose

Below is a sample docker-compose.yml segment to add the required services for Celery workers, Celery-Beat, and Redis:

```yml
version: '3'

# 3 name volumes are named here.
volumes:
    volume_postgresdata:        # Store the postgres database data. Only linked with postgres.
    volume_django_media:        # Store the Django media files. Volume is shared between djangoweb and nginx.
    volume_django_static:       # Store the Django static files. Volume is shared between djangoweb and nginx.

services:
    # Postgresql database settings.
    postgresdb:
        image: postgres:9.6-alpine
        environment:
            - POSTGRES_DB
            - POSTGRES_USER
            - POSTGRES_PASSWORD
        restart: unless-stopped
        volumes:
            - volume_postgresdata:/var/lib/postgresql/data
        ports:
            - "127.0.0.1:5432:5432"
        networks:
            - backend

    # Django settings.
    djangoweb:
        build:
            context: .
            args:
                - DJANGO_ENVIRONMENT=${DJANGO_ENVIRONMENT:-production}
        image: djangoapp:latest
        networks:
            - backend
            - celery
            - frontend
        volumes:
            - .:/app/
            - volume_django_static:/var/staticfiles
            - volume_django_media:/var/mediafiles
        ports: # IMPORTANT: Make sure to use 127.0.0.1 to keep it local. Otherwise, this will be broadcast to the web.
            - 127.0.0.1:8000:8000
        depends_on:
            - postgresdb
            - mailhog
        environment:
            - POSTGRES_DB
            - POSTGRES_USER
            - POSTGRES_PASSWORD
            - POSTGRES_HOST=postgresdb # Name of the postgresql service.
            - POSTGRES_PORT
            - DJANGO_SETTINGS_MODULE
            - FORCE_SCRIPT_NAME
            - DJANGO_ENVIRONMENT
            - SECRET_KEY
            - DJANGO_ALLOWED_HOSTS
        links:
            - "postgresdb"

    # add redis as a message broker
    redis:
        image: "redis:alpine"
        networks:
            - celery

    # celery worker process -- launches child celery processes equal to the number of available cores
    celery:
        build:
            context: .
            dockerfile: Dockerfile.celery
            args:
                - DJANGO_ENVIRONMENT=${DJANGO_ENVIRONMENT:-production}
        command: celery -A django_cog worker -l info
        image: djangoapp_celery:latest
        volumes:
            - .:/app/
        environment:
            - POSTGRES_DB
            - POSTGRES_USER
            - POSTGRES_PASSWORD
            - POSTGRES_HOST=postgresdb # Name of the postgresql service.
            - POSTGRES_PORT
            - FORCE_SCRIPT_NAME
            - DJANGO_ENVIRONMENT
            - DJANGO_SETTINGS_MODULE
            - SECRET_KEY
            - DJANGO_ALLOWED_HOSTS
        depends_on:
            - postgresdb
            - redis
        networks:
            - backend
            - celery
        links:
            - "postgresdb"

    # celery worker process -- launches child celery processes equal to the number of available cores
    celerybeat:
        build:
            context: .
            dockerfile: Dockerfile.celery
            args:
                - DJANGO_ENVIRONMENT=${DJANGO_ENVIRONMENT:-production}
        command: celery -A django_cog beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
        image: djangoapp_celerybeat:latest
        volumes:
            - .:/app/
        environment:
            - POSTGRES_DB
            - POSTGRES_USER
            - POSTGRES_PASSWORD
            - POSTGRES_HOST=postgresdb # Name of the postgresql service.
            - POSTGRES_PORT
            - FORCE_SCRIPT_NAME
            - DJANGO_ENVIRONMENT
            - DJANGO_SETTINGS_MODULE
            - SECRET_KEY
            - DJANGO_ALLOWED_HOSTS
        depends_on:
            - celery
        networks:
            - backend
            - celery

networks:
    frontend:
        name: djangocog_frontend
    backend:
        name: djangocog_backend
    celery:
        name: djangocog_celery
```

And the matching `Dockerfile.celery` (of which the `celery` and `celerybeat` services will build from):
```dockerfile
FROM python:3.8
ENV PYTHONUNBUFFERED 1

ARG DJANGO_ENVIRONMENT

# Make the static/media folder.
RUN mkdir /var/staticfiles
RUN mkdir /var/mediafiles

# Make a location for all of our stuff to go into
RUN mkdir /app

# Set the working directory to this new location
WORKDIR /app

# Add our Django code
ADD . /app/

RUN pip install --upgrade pip

# Install requirements for Django
RUN pip install -r requirements/base.txt
RUN pip install -r requirements/${DJANGO_ENVIRONMENT}.txt
RUN pip install -r requirements/custom.txt

# No need for an entry point as they are defined in the docker-compose.yml services
```

## Queues

You can create specific queues within celery, and assign tasks to these queues.  Within the `Task` Django admin, you'll find a `queue` field that defaults to `celery`.  This is the default queue that celery works on.  This queue option is created automatically and is used as the default when you run the django-cog migrations.

#### Adding Queues

If you want to have a separate collection of workers dedicated for certain tasks, create a new `CeleryQueue` record in the Django admin and set your tasks to this queue.

Additionally, you'll need workers to work on this queue.  You can do this by adding a `-Q queue_name` parameter to the `command` call in the `docker-compose.yml` file's `celery` service:

```yml
services:
    celery:
        command: celery -A django_cog worker -l info -Q queue_name
```


## Task Optimization and Weights

In order to achieve better runtimes, tasks are queued in order of greatest "weight" first.  This works best in scenarios where you have some `n` number of tasks that have a longer run time, but have extra tasks whose summation runtimes do not exceed that of the longer tasks.  The longer tasks will be launched first, allowing the runtime of each stage to be in direct correlation of the longest running individual task, rather than an arbitrary coefficient of shorter tasks that happened to be queued up before it.

The weight of a task is updated at the end of each of its Pipeline run completions.  The `weight` field of a `Task` is literally the average number of total seconds it took to complete.  (NOTE: This field is limited to 11 decimal places with a precision of 5 points, which means the maximum runtime supported for a single task is roughly 11.5 days).

The sample size taken defaults to the past 10 runtimes of that task, but this can be adjusted by adding the following to your Django `settings.py`:
```python
DJANGO_COG_TASK_WEIGHT_SAMPLE_SIZE = 10
```

If you do not want to have the weight auto-calculated, you can disable this calculation by adding the following to your Django `settings.py`:
```python
DJANGO_COG_AUTO_WEIGHT = False
```

Note: Tasks will still be ordered by weight (descending) when queued, but they all default to a weight of `1` prior to any runs.  You can also manually adjust this weight through the `Task` Django admin, which enables you to determine the order of queuing yourself (which of course requires the disabling of auto-weight calculation, as described above).