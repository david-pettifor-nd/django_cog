from django.db import models
import uuid
import json

from django_celery_beat.models import CrontabSchedule, PeriodicTask
import datetime
import pytz
from . import TASK_WEIGHT_SAMPLE_SIZE
from django.conf import settings


class CeleryQueue(models.Model):
    """
    A way to control which queue goes where.
    The default queue django-celery uses is "celery".
    If you want to follow a specific queue, call celery with
    the "-Q queue_name" parameter.
    """
    queue_name = models.CharField(max_length=4096)

    def __str__(self):
        return self.queue_name


class DefaultBaseModel(models.Model):
    """
    Abstract base model that is used to add `created_date`
    and `modified_date` fields to all decendent models.
    Also uses UUID4 for the ID
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Cog(DefaultBaseModel):
    """
    A way to keep track of registered cogs
    """
    name = models.CharField(max_length=4096)

    def __str__(self):
        return self.name


class CogErrorHandler(DefaultBaseModel):
    """
    A way to keep track of registered cogs error handlers
    """
    name = models.CharField(max_length=4096)

    def __str__(self):
        return self.name


class Pipeline(DefaultBaseModel):
    """
    A collection of stages all linked together.
    A pipeline is what gets called via a cron schedule
    """
    schedule = models.ForeignKey(CrontabSchedule, null=True, blank=True, on_delete=models.CASCADE)
    name = models.CharField(max_length=4096)
    enabled = models.BooleanField(default=True)
    prevent_overlapping_runs = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """
        Upon saving, make sure we create the cron schedule.
        """
        # then create the PeriodicTask
        #   NOTE: Use the UUID of this pipeline as the name,
        #   which will make deleting it safer
        if self.schedule:
            periodic_task, created = PeriodicTask.objects.get_or_create(
                name=self.id,
                defaults={
                    'crontab': self.schedule
                }
            )
            periodic_task.crontab = self.schedule
            periodic_task.task = 'django_cog.launch_pipeline'
            periodic_task.args = json.dumps([str(self.id)])
            periodic_task.kwargs = json.dumps({
                'pipeline_id': str(self.id)
            })
            periodic_task.enabled = self.enabled
            periodic_task.save()
        else:
            # remove any periodic tasks that may have been previously
            # created
            PeriodicTask.objects.filter(
                name=self.id
            ).delete()

        super(Pipeline, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Upon deleting, make sure to remove the created PeriodicTask.
        """
        # delete the periodic task that was created from this pipeline
        if PeriodicTask.objects.filter(name=self.id).exists():
            PeriodicTask.objects.filter(name=self.id).delete()
        
        # then delete the pipeline object
        super(Pipeline, self).delete(*args, **kwargs)


class Stage(DefaultBaseModel):
    """
    A stage is an ordered element of a pipeline, and will
    consist of a collection of cogs.  Cogs in the same
    stage are processes that can be ran independently of each other.

    When one stage of a pipeline completes, the next stage is began.

    Here, "proceeds" will point to the PREVIOUS stage.
        - NULL will mean it is the first stage to launch at the start of the pipeline.
    """
    name = models.CharField(max_length=4096)
    pipeline = models.ForeignKey(Pipeline, related_name='stages', on_delete=models.CASCADE)
    launch_after_stage = models.ManyToManyField('Stage', related_name='next_stage', blank=True)

    def __str__(self):
        return f"{self.pipeline} - {self.name}"
    
    class Meta:
        ordering = ['pipeline', 'name']


class Task(DefaultBaseModel):
    """
    A specific registered function to tie to a stage.

    - Prevent Overlapping Calls:
        If true, the function defined in the Cog will not be called if we detect
        a TaskRun has not yet completed with the same Cog definition.
    """
    name = models.CharField(max_length=4096, blank=True, null=True)
    cog = models.ForeignKey(Cog, related_name='assigned_tasks', on_delete=models.CASCADE)
    stage = models.ForeignKey(Stage, related_name='assigned_tasks', on_delete=models.CASCADE)
    error_handler = models.ForeignKey(CogErrorHandler, related_name='tasks', on_delete=models.SET_NULL, null=True, blank=True)
    arguments_as_json = models.TextField(blank=True, null=True)
    prevent_overlapping_calls = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    queue = models.ForeignKey(CeleryQueue, related_name='assigned_tasks', on_delete=models.SET_NULL, default=1, null=True)
    weight = models.DecimalField(decimal_places=5, max_digits=12, default=1.0)
    critical = models.BooleanField(default=True)

    def __str__(self):
        if self.name:
            return self.name
        return str(self.cog)


# //-- Below are records kept for execution runs --//
class EntityRun(DefaultBaseModel):
    """
    Base model for runs.  Includes a start and completed on.
    """
    STATUS_OPTIONS = [
        ('Queued', 'Queued'),
        ('Running', 'Running'),
        ('Failed', 'Failed'),
        ('Completed', 'Completed'),
        ('Canceled', 'Canceled')
    ]
    started_on = models.DateTimeField(auto_now_add=True)
    completed_on = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Queued', null=True)
    
    def __str_runtimes__(self):
        string = f"[{self.started_on}]"
        if self.completed_on:
            string += ' COMPLETED'
        return string

    def runtime(self):
        if self.completed_on:
            return (self.completed_on - self.started_on)
        return None
    
    class Meta:
        ordering = ['-completed_on', '-started_on']

class PipelineRun(EntityRun):
    """
    Specific execution run of a pipeline.
    """
    pipeline = models.ForeignKey(Pipeline, related_name='runs', on_delete=models.CASCADE)
    success = models.NullBooleanField()

    def __str__(self):
        return f"{str(self.pipeline)} {self.__str_runtimes__()}"
    
    def save(self, *args, **kwargs):
        # how many tasks need to be completed?
        required = self.pipeline.stages.all().count()
        completed = self.stage_runs.filter(
            completed_on__isnull=False
        ).count()
        if required == completed:
            self.completed_on = datetime.datetime.now(tz=pytz.UTC)

            # did we complete successfully?  if we're here and haven't been set to false yet,
            # then we can assume it's all good
            if self.success is None:
                self.success = True

            # if we were running (haven't failed critically), update to completed
            if self.status == 'Running':
                self.status = 'Completed'

            # do we want to auto-update weight?
            if not hasattr(settings, 'DJANGO_COG_AUTO_WEIGHT') or settings.DJANGO_COG_AUTO_WEIGHT:
                # pull the weight sample size
                sample_size = TASK_WEIGHT_SAMPLE_SIZE
                if hasattr(settings, 'DJANGO_COG_TASK_WEIGHT_SAMPLE_SIZE'):
                    sample_size = settings.DJANGO_COG_TASK_WEIGHT_SAMPLE_SIZE

                # make a way to compute runtime from SQL:
                duration = models.ExpressionWrapper(
                    models.F('completed_on') - models.F('started_on'),
                    output_field=models.fields.DurationField()
                )

                # if we're completed, let's update the weights of all our tasks
                for stage in self.pipeline.stages.all():
                    # update each tasks in the stage
                    for task in stage.assigned_tasks.all():
                        # do we have any runs that we can actually base an update off of?
                        if not task.runs.filter(task__enabled=True).exists():
                            continue

                        # get a sample of this tasks runs
                        average_weight = task.runs.filter(
                            task__enabled=True
                        )[:sample_size].annotate(
                            runtime=duration
                        ).aggregate(models.Avg('runtime'))['runtime__avg'].total_seconds()
                        task.weight  = average_weight
                        task.save()
        super(PipelineRun, self).save(*args, **kwargs)

class StageRun(EntityRun):
    """
    Specific execution run of a stage.
    """
    pipeline_run = models.ForeignKey(PipelineRun, related_name='stage_runs', on_delete=models.CASCADE)
    stage = models.ForeignKey(Stage, related_name='runs', on_delete=models.CASCADE)
    success = models.NullBooleanField()

    def __str__(self):
        return f"{str(self.stage)} {self.__str_runtimes__()}"
    
    def save(self, *args, **kwargs):
        # how many tasks need to be completed?
        required = self.stage.assigned_tasks.filter(enabled=True).count()
        completed = self.task_runs.filter(
            completed_on__isnull=False
        ).count()
        if required == completed and self.completed_on is None:
            self.completed_on = datetime.datetime.now(tz=pytz.UTC)

            # did we complete it successfully?  default is yes unless we've been set
            # to false by a failed task already
            if self.success is None:
                self.success = True
            
            # if we were running (haven't failed critically), update to completed
            if self.status == 'Running':
                self.status = 'Completed'

            # call the super to make sure that when we launch the next stage,
            # it knows we're done, and will be counted then
            super(StageRun, self).save(*args, **kwargs)

            # make sure that any crashed tasks weren't critical...
            required_completed = True
            for task in self.task_runs.filter(success=False):
                if task.task.critical:
                    print("!! Found crashed tasks that are marked critical, so we are not launching the next stage!")
                    required_completed = False
            
            # and make sure we haven't had a call for cancellation yet...
            canceled = False
            if self.pipeline_run.status == 'Canceled':
                print("!! Found pipeline run in canceled state, so we are not launching the next stage.")
                self.status = 'Canceled'
                canceled = True

            # if this is the case, we can call the next stages!
            if required_completed and not canceled and self.stage.next_stage.all().count() > 0:
                from django_cog import launch_stage
                for stage in self.stage.next_stage.all():
                    launch_stage.delay(stage_id=stage.id, pipeline_run_id=self.pipeline_run.id)

        else:
            # if we were canceled, the completed on time would be filled in.  we just need to
            # mark ourselves as canceled now as well:
            if self.pipeline_run.status == 'Canceled':
                self.status = 'Canceled'

            # make sure to save this run in case we haven't completed yet...so our tasks
            # we're about to launch know who they belong to
            super(StageRun, self).save(*args, **kwargs)

        # trigger the pipeline run save just in case this is the last stage
        # note: we must do this after calling the super, so the pipeline run can pick up
        #   that we've completed this stage run
        self.pipeline_run.save()


class TaskRun(EntityRun):
    """
    Specific execution run of a task.
    """
    stage_run = models.ForeignKey(StageRun, related_name='task_runs', on_delete=models.CASCADE)
    task = models.ForeignKey(Task, related_name='runs', on_delete=models.CASCADE)
    success = models.NullBooleanField()

    def __str__(self):
        return f"{str(self.task)} {self.__str_runtimes__()}"


class CogError(DefaultBaseModel):
    """
    Support for default cog error handler.
    Stores information about the error in the database.
    """
    task_run = models.ForeignKey(TaskRun, related_name='errors', on_delete=models.CASCADE, null=True, blank=True)
    timestamp = models.DateTimeField(auto_created=True, auto_now_add=True)
    error_type = models.CharField(max_length=1024, blank=True, null=True)
    traceback = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.task_run.task.name} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    class Meta:
        ordering = ['-timestamp']