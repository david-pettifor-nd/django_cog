from .celery import celery_app as celery_app
from celery.decorators import task
import datetime
import pytz
import json
import traceback
import inspect

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


def CogErrorHandlerRegistration():
    """
    Decorator used to register error handlers.

    Shamelessly stolen from: https://stackoverflow.com/questions/5707589/calling-functions-by-array-index-in-python/5707605#5707605
    """
    registry = {}
    def registrar(func):
        registry[func.__name__] = func
        return func  # normally a decorator returns a wrapped function, 
                     # but here we return func unmodified, after registering it
    registrar.all = registry
    return registrar

cog_error_handler = CogErrorHandlerRegistration()


@cog_error_handler
def defaultCogErrorHandler(error, task_run=None):
    """
    Default cog error handler.  Records the error's type, time, and traceback
    into the database.
    """
    from .models import CogError
    error_info = "".join(traceback.format_exception(etype=None, value=error, tb=error.__traceback__))
    CogError.objects.create(
        task_run=task_run,
        traceback=error_info,
        error_type=type(error).__name__
    )


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
    
    # make sure a previous task hasn't failed, if it's critical
    for previous_task in stage_run.task_runs.filter(success=False):
        if previous_task.task.critical:
            print("!! A previously crashed task was critical to the pipeline, so we're aborting.")
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
        # if there's an error handler for this function, pass what ever sort of Exception we got
        # into the handler
        if task.error_handler:
            try:
                signature = inspect.signature(cog_error_handler.all[task.error_handler.name])
                if 'task_run' in signature.parameters:
                    cog_error_handler.all[task.error_handler.name](e, task_run=task_run)
                else:
                    cog_error_handler.all[task.error_handler.name](e)
            except Exception as error_handler_error:
                print("!! Failed to execute error handler!  Make sure it has only one parameter to take in (the error Exception)")
                print(error_handler_error)
        else:
            # do we at least have the default one that should come with this library? (like..it's literally defined above)
            if 'defaultCogErrorHandler' in cog_error_handler.all:
                # then we can use this as our default
                cog_error_handler.all['defaultCogErrorHandler'](e, task_run=task_run)

        # save this task run as having failed
        task_run.success = False
        task_run.save()

        # also mark the stage and pipelines
        stage_run.success = False
        stage_run.save()
        stage_run.pipeline_run.success = False
        stage_run.pipeline_run.save()
    
    # mark that this task is completed
    task_run.completed_on = datetime.datetime.now(tz=pytz.UTC)

    # mark it successful unless it failed above
    if task_run.success is None:
        task_run.success = True
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
        print("== FROM STAGE:", task.name, task.critical)
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
