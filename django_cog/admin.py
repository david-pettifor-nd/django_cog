from django.contrib import admin
from .models import (
    Cog,
    Pipeline,
    Stage,
    Task,
    PipelineRun,
    StageRun,
    TaskRun
)

# Register your models here.

@admin.register(Cog)
class CogAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ["name", "schedule", "enabled"]
    search_fields = ["name"]


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ["name", "pipeline"]
    search_fields = ["name"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["task_name", "cog", "stage", "pipeline"]
    search_fields = ["cog"]

    def pipeline(self, obj):
        return obj.stage.pipeline
    
    def task_name(self, obj):
        if obj.name:
            return obj.name
        return obj.cog


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ["pipeline", "started_on", "completed_on", "runtime"]
    search_fields = ["pipeline", "started_on"]


@admin.register(StageRun)
class StageRunAdmin(admin.ModelAdmin):
    list_display = ["stage", "pipeline", "started_on", "completed_on", "runtime"]
    search_fields = ["stage", "pipeline", "started_on"]

    def pipeline(self, obj):
        return obj.pipeline_run.pipeline


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ["task", "stage", "pipeline", "started_on", "completed_on", "runtime"]
    search_fields = ["task", "stage", "pipeline", "started_on"]

    def pipeline(self, obj):
        return obj.stage_run.pipeline_run.pipeline
    
    def stage(self, obj):
        return obj.stage_run.stage
