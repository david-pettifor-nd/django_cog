import functools
from .celery import celery_app as celery_app
from celery.decorators import task
import datetime
import pytz
import json

__all__ = ['celery_app']

# default sample for calculating weight of tasks
TASK_WEIGHT_SAMPLE_SIZE = 10


def CogRegistration():
    """
    Decorator used to register tasks.

    Shamelessly stolen from: https://stackoverflow.com/questions/5707589/calling-functions-by-array-index-in-python/5707605#5707605
    """
    registry = {}
    def registrar(func):
        registry[func.__name__] = func
        return func  # normally a decorator returns a wrapped function, 
                     # but here we return func unmodified, after registering it
    registrar.all = registry
    return registrar

cog = CogRegistration()


# //-- Below are the Celery tasks used to launch Tasks, Stages, and Pipelines --//
@task
def launch_task(task_id, stage_run_id):
    """
    Main celery task called when launching a new stage.
    """
    from .models import Task, TaskRun, StageRun
    # look up the task
    try:
        task = Task.objects.get(id=task_id)
    except Task.DoesNotExist:
        print("!! Could not find task called.  Aboring.")
        exit()
    
    # is this enabled?
    if not task.enabled:
        return
    
    # look up the stage ruin
    try:
        stage_run = StageRun.objects.get(id=stage_run_id)
    except StageRun.DoesNotExist:
        print("!! Could not find stage run called.  Aboring.")
        exit()
    
    # do we already have a task running that hasn't completed (and do we care)?
    # note: this check is cross-stage checking.  Really, this shouldn't ever fire off
    # unless we start a new run of the Pipeline before a previous one has finished,
    # OR this task is part of a different pipeline.
    if task.prevent_overlapping_calls and TaskRun.objects.filter(task=task, completed_on__isnull=True).exists():
        print("!! Another instance of this task has not completed yet.  Aborting.")
        exit()
    
    # otherwise, create a new pipeline run
    task_run = TaskRun.objects.create(
        stage_run=stage_run,
        task=task
    )

    # get the function in our `cog` that matches the name
    try:
        kwargs = {}
        if task.arguments_as_json:
            kwargs = json.loads(task.arguments_as_json)
        cog.all[task.cog.name](**kwargs)
    except Exception as e:
        print("!! Task failed:", e)
    
    # mark that this task is completed
    task_run.completed_on = datetime.datetime.now(tz=pytz.UTC)
    task_run.save()

    # trigger the save on our stage run so we can check if we're done with all of our tasks
    stage_run.save()

@task
def launch_stage(stage_id, pipeline_run_id):
    """
    Main celery task called when launching a new stage.
    """
    from .models import Stage, StageRun, PipelineRun
    # look up the stage
    try:
        stage = Stage.objects.get(id=stage_id)
    except Stage.DoesNotExist:
        print("!! Could not find stage called.  Aboring.")
        exit()
    
    # look up the pipeline run
    try:
        pipeline_run = PipelineRun.objects.get(id=pipeline_run_id)
    except PipelineRun.DoesNotExist:
        print("!! Could not find pipeline run called.  Aboring.")
        exit()
    
    # make sure all previous stage runs have completed
    for required_stage in stage.launch_after_stage.all():
        if not StageRun.objects.filter(
            stage=required_stage,
            pipeline_run=pipeline_run,
            completed_on__isnull=False
        ).exists():
            # if there isn't a run that is completed, then abort
            # (once this required stage run completes, this function
            #   will be called again)
            return
    
    # otherwise, create a new pipeline run
    stage_run = StageRun.objects.create(
        stage=stage,
        pipeline_run=pipeline_run
    )

    # order tasks by their weight
    # this ensures the longest tasks get called first, which helps improve overall runtime
    tasks = stage.assigned_tasks.filter(enabled=True).order_by('-weight')
    # launch all tasks concurrently
    for task in tasks:
        # assume default ("celery") queue, unless specified
        queue = 'celery'
        if task.queue:
            queue = task.queue.queue_name
        launch_task.apply_async(
            queue = queue,
            kwargs = {
                'task_id': task.id,
                'stage_run_id': stage_run.id
            }
        )

@celery_app.task
def launch_pipeline(*args, **kwargs):
    """
    Main django-celery-beat function called when a pipeline is ready to launch
    """
    if 'pipeline_id' not in kwargs:
        print("!! Incorrect calling of function.  Could not find pipeline identifier.")
        exit()

    from .models import Pipeline, PipelineRun
    # look up the pipeline
    try:
        pipeline = Pipeline.objects.get(id=kwargs['pipeline_id'])
    except Pipeline.DoesNotExist:
        print("!! Could not find pipeline called.  Aboring.")
        exit()
    
    # is this pipeline enabled, and do we check for it?
    if 'user_initiated' not in kwargs and not pipeline.enabled:
        print("Pipeline not enabled.  Aborting.")
        return
    
    # is there another run of this pipline still going? (and do we care?)
    if pipeline.prevent_overlapping_runs and PipelineRun.objects.filter(
        pipeline=pipeline,
        completed_on__isnull=True
    ).exists():
        print("!! Another instance of this pipeline has not completed.  Aborting.")
        return

    # otherwise, create a new pipeline run
    pipeline_run = PipelineRun.objects.create(
        pipeline=pipeline
    )

    # start the first stage
    first_stages = pipeline.stages.filter(
        launch_after_stage=None
    )
    for stage in first_stages:
        # theoritically, you should never have more than one stage,
        # because all tasks could be bundled into a single stage
        launch_stage.delay(stage_id=stage.id, pipeline_run_id=pipeline_run.id)
