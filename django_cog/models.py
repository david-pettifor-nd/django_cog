from django.db import models
import uuid
import json
from django_celery_beat.models import CrontabSchedule, PeriodicTask
import datetime
import pytz


# Create your models here.
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


class Pipeline(DefaultBaseModel):
    """
    A collection of stages all linked together.
    A pipeline is what gets called via a cron schedule
    """
    schedule = models.ForeignKey(CrontabSchedule, on_delete=models.CASCADE)
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
        periodic_task, created = PeriodicTask.objects.get_or_create(
            name=self.name,
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
        super(Pipeline, self).save(*args, **kwargs)


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
    launch_after_stage = models.ManyToManyField('Stage', related_name='next_stage')

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
    arguments_as_json = models.TextField(blank=True, null=True)
    prevent_overlapping_calls = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        if self.name:
            return self.name
        return str(self.cog)


# //-- Below are records kept for execution runs --//
class EntityRun(DefaultBaseModel):
    """
    Base model for runs.  Includes a start and completed on.
    """
    started_on = models.DateTimeField(auto_now_add=True)
    completed_on = models.DateTimeField(null=True, blank=True)
    
    def __str_runtimes__(self):
        string = f"[{self.started_on}]"
        if self.completed_on:
            string += ' COMPLETED'
        return string


class PipelineRun(EntityRun):
    """
    Specific execution run of a pipeline.
    """
    pipeline = models.ForeignKey(Pipeline, related_name='runs', on_delete=models.CASCADE)

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

        super(PipelineRun, self).save(*args, **kwargs)


class StageRun(EntityRun):
    """
    Specific execution run of a stage.
    """
    pipeline_run = models.ForeignKey(PipelineRun, related_name='stage_runs', on_delete=models.CASCADE)
    stage = models.ForeignKey(Stage, related_name='runs', on_delete=models.CASCADE)

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

            # call the super to make sure that when we launch the next stage,
            # it knows we're done, and will be counted then
            super(StageRun, self).save(*args, **kwargs)

            # if this is the case, we can call the next stages!
            if self.stage.next_stage.all().count() > 0:
                from django_cog import launch_stage
                for stage in self.stage.next_stage.all():
                    launch_stage.delay(stage_id=stage.id, pipeline_run_id=self.pipeline_run.id)

        else:
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

    def __str__(self):
        return f"{str(self.task)} {self.__str_runtimes__()}"